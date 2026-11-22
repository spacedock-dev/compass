import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mountPanels } from '../steering/testing';
import { CapacityStrip } from './CapacityStrip';
import { heldFor } from './held';

/* What the strip refuses to say, and what the reader keeps. A window that publishes no clock draws no tick;
   an unmeasured pace is not a zero and a measured zero is not unmeasured; a reset already past removes the
   claim instead of clamping it; a spent budget says so. The selected window is the reader's: held by vendor
   and window across a redraw that reorders it, below the initial three rows, and a route change. */
const NOW = 1_800_000_000;
const window = (pct: number, resetIn: number | null, length: number | null, extra = {}) => ({
  pct,
  ...(length === null ? {} : { windowSec: length }),
  ...(resetIn === null ? {} : { resetAt: NOW + resetIn }),
  ...extra,
});
const entry = (harness: string, windows: Record<string, unknown>, extra = {}) => ({
  harness,
  state: 'ok',
  asOf: NOW - 30,
  ...windows,
  ...extra,
});
const board = (usage: unknown[], over: Record<string, unknown> = {}) => ({
  generated: NOW,
  harnesses: [
    { key: 'claude', label: 'Claude Code' },
    { key: 'cursor', label: 'Cursor' },
    { key: 'codex', label: 'Codex' },
  ],
  usage,
  sessions: [],
  ...over,
});
const rowKeys = (): string[] =>
  [...document.querySelectorAll('[data-next-capacity-row]')].map(
    (row) => (row as HTMLElement).dataset['nextCapacityRow'] ?? '',
  );
const pressed = (): string[] =>
  [...document.querySelectorAll('button[aria-pressed="true"]')].map(
    (button) => (button as HTMLElement).dataset['nextCapacityPick'] ?? '',
  );
const rowOf = (key: string): HTMLElement =>
  document.querySelector(`[data-next-capacity-row="${key}"]`) as HTMLElement;

// Six windows, ranked by when each budget ends: the three last are untimed or slow.
const six = () =>
  board([
    entry('claude', { fiveH: window(50, 9000, 18000), week: window(10, 3 * 86400, 604800) }),
    entry('cursor', { fiveH: window(90, 3000, 18000), month: window(40, null, null) }),
    entry('codex', { fiveH: window(20, 12000, 18000), week: window(30, 4 * 86400, 604800) }),
  ]);

describe('the selected window is the reader’s', () => {
  it('draws the first window selected, and keeps a window below the initial three where it is chosen', async () => {
    const page = mountPanels(<CapacityStrip />, { data: six(), strict: false });
    await page.settle();
    expect(rowKeys()).toHaveLength(3);
    expect(pressed()).toEqual([rowKeys()[0]]);
    expect(document.querySelector('.next-capacity-more')?.textContent).toMatch(/^3 more windows/);
    // A window ranked fifth is chosen through the lane the way a press would: it takes the last visible place.
    const lane = heldFor(page.shell.runtime).selection;
    const all = [...document.querySelectorAll('[data-next-capacity-row]')];
    expect(all).toHaveLength(3);
    lane.set('claude:week');
    await page.settle();
    expect(pressed()).toEqual(['claude:week']);
    expect(rowKeys()).toHaveLength(3);
    expect(rowKeys()).toContain('claude:week');
    // The rest are still counted, over the withheld rows only.
    expect(document.querySelector('.next-capacity-more')?.textContent).toMatch(/^3 more windows/);
  });

  it('survives a poll that reorders every window', async () => {
    const page = mountPanels(<CapacityStrip />, { data: six(), strict: false });
    await page.settle();
    fireEvent.click(rowOf(rowKeys()[1] as string));
    const chosen = pressed()[0];
    expect(chosen).toBeDefined();
    const name = screen.getByRole('progressbar').getAttribute('aria-label');
    await page.poll(
      board([
        entry('codex', { fiveH: window(95, 1000, 18000), week: window(30, 4 * 86400, 604800) }),
        entry('cursor', { fiveH: window(5, 3000, 18000), month: window(40, null, null) }),
        entry('claude', { fiveH: window(50, 9000, 18000), week: window(10, 3 * 86400, 604800) }),
      ]),
    );
    expect(pressed()).toEqual([chosen]);
    expect(screen.getByRole('progressbar').getAttribute('aria-label')).toBe(name);
    expect(heldFor(page.shell.runtime).selection.read()).toBe(chosen);
  });

  it('a window button chooses it without a request', async () => {
    const page = mountPanels(<CapacityStrip />, { data: six(), strict: false });
    await page.settle();
    const before = page.state.requests.length;
    const target = rowKeys()[2] as string;
    fireEvent.click(rowOf(target));
    expect(pressed()).toEqual([target]);
    expect(page.state.requests.length).toBe(before);
    expect(page.allPosts()).toEqual([]);
  });

  it('falls back to an existing window only when its own is gone, holds the fallback, and clears when none remain', async () => {
    const page = mountPanels(<CapacityStrip />, { data: six(), strict: false });
    await page.settle();
    const lane = heldFor(page.shell.runtime).selection;
    lane.set('cursor:fiveH');
    await page.settle();
    expect(lane.read()).toBe('cursor:fiveH');
    await page.poll(
      board([
        entry('claude', { fiveH: window(50, 9000, 18000), week: window(10, 3 * 86400, 604800) }),
      ]),
    );
    expect(pressed()).toHaveLength(1);
    expect(lane.read()).toBe(pressed()[0]);
    expect(lane.read()).not.toBe('cursor:fiveH');
    // The fallback is now the reader's choice: the vanished window returning does not take it back.
    await page.poll(six());
    expect(pressed()).toEqual([lane.read()]);
    await page.poll(board([]));
    expect(document.querySelector('[data-next-capacity]')).toBeNull();
    expect(lane.read()).toBe('');
  });

  it('an unread board is not a board with no windows: it clears nothing', async () => {
    const page = mountPanels(<CapacityStrip />, { data: undefined, strict: false });
    heldFor(page.shell.runtime).selection.set('claude:week');
    await page.settle();
    expect(heldFor(page.shell.runtime).selection.read()).toBe('claude:week');
  });

  it('is kept across a route change that unmounts the strip', async () => {
    const page = mountPanels(<CapacityStrip />, { data: six() });
    await page.settle();
    const target = rowKeys()[1] as string;
    fireEvent.click(rowOf(target));
    page.show(<p>Elsewhere</p>);
    await page.settle();
    page.show(<CapacityStrip />);
    await page.settle();
    expect(pressed()).toEqual([target]);
  });

  it('keeps keyboard focus on the chosen window across the redraw that reorders it', async () => {
    const page = mountPanels(<CapacityStrip />, { data: six(), strict: false });
    await page.settle();
    const target = rowKeys()[0] as string;
    const button = rowOf(target);
    button.focus();
    fireEvent.click(button);
    await page.poll(
      board([
        entry('codex', { fiveH: window(95, 1000, 18000) }),
        entry('cursor', { fiveH: window(95, 1500, 18000) }),
        entry('claude', { fiveH: window(95, 2000, 18000), week: window(10, 3 * 86400, 604800) }),
      ]),
    );
    await page.settle();
    expect(document.activeElement?.getAttribute('data-next-capacity-pick')).toBe(target);
  });
});

describe('absent, stale, expired and true zero are four different things', () => {
  const only = (windows: Record<string, unknown>, extra = {}) =>
    mountPanels(<CapacityStrip />, {
      data: board([entry('claude', windows, extra)]),
      strict: false,
    });

  it('a window with no clock draws no tick, no pace and no projection, and says each is absent', async () => {
    const page = only({ month: window(40, null, null) });
    await page.settle();
    expect(document.querySelector('.next-capacity-tick')).toBeNull();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuetext')).toBe(
      '40% of budget used, this window publishes no clock',
    );
    fireEvent.click(screen.getByRole('button', { name: 'How the AI allowance works' }));
    expect(screen.getByText('Pace not measured')).toBeVisible();
    expect(screen.getByText('Not projected')).toBeVisible();
    expect(screen.getByText('Not published', { exact: true })).toBeVisible();
    expect(screen.getByText('billing cycle · length not published')).toBeVisible();
    // With no pace there is no prospect to state.
    expect(document.querySelector('.next-capacity-prospect')).toBeNull();
  });

  it('a reset already past leaves the window untimed rather than clamping it into a false all-clear', async () => {
    const page = only({ fiveH: window(30, -60, 18000) });
    await page.settle();
    expect(document.querySelector('.next-capacity-tick')).toBeNull();
    expect(
      screen.getByText('Claude Code 5-hour plan · the published reset has passed.'),
    ).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'How the AI allowance works' }));
    expect(screen.getByText('Not projected')).toBeVisible();
    expect(screen.getByText(/\(passed\)/)).toBeVisible();
    expect(document.body.textContent).not.toContain('spare');
  });

  it('a spent budget says so and does not print the present minute as a deadline', async () => {
    const page = only({ fiveH: window(100, 9000, 18000) });
    await page.settle();
    fireEvent.click(screen.getByRole('button', { name: 'How the AI allowance works' }));
    expect(screen.getByText('Already spent')).toBeVisible();
  });

  it('a true zero used is a figure, not an absence', async () => {
    const page = only({ fiveH: window(0, 9000, 18000) });
    await page.settle();
    expect(screen.getByText('0% used')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'How the AI allowance works' }));
    expect(screen.getByText('0.0×')).toBeVisible();
    expect(screen.getByText('Not projected')).toBeVisible();
  });

  it('a recent pace measured at zero is evidence; an absent one is only absence', async () => {
    const flat = only({
      fiveH: window(30, 9000, 18000, { recent: { pctPerMin: 0, samples: 4, spanSec: 1800 } }),
    });
    await flat.settle();
    expect(document.querySelector('.next-capacity-prospect small')?.textContent).toBe(
      'Recent pace measured at zero: nothing spent across 30m and 4 readings, so nothing is projected from it.',
    );
    flat.unmount();
    const absent = only({ fiveH: window(30, 9000, 18000) });
    await absent.settle();
    expect(document.querySelector('.next-capacity-prospect small')?.textContent).toBe(
      'Recent pace not measured: no second reading yet from this vendor.',
    );
  });

  it('prints neither caption when nothing says when the reading was taken', async () => {
    const page = only({ fiveH: window(30, 9000, 18000) }, { asOf: null });
    await page.settle();
    expect(document.querySelector('.next-capacity-prospect small')).toBeNull();
  });

  it('a recent pace that was published is a second projection, with its span, beside the average', async () => {
    const page = only({
      fiveH: window(30, 9000, 18000, { recent: { pctPerMin: 0.2, samples: 3, spanSec: 600 } }),
    });
    await page.settle();
    const prospect = document.querySelector('.next-capacity-prospect')?.textContent ?? '';
    expect(prospect).toContain("at this window's average pace, or");
    expect(prospect).toContain('at the recent pace (last 10m)');
    expect(screen.getByText('Claude Code 5-hour plan · resets in 2h 30m.')).toBeVisible();
    expect(document.querySelector('.next-capacity-prospect small')).toBeNull();
  });

  it('a thin basis qualifies the time and the spare together', async () => {
    const page = only({ fiveH: window(2, 17700, 18000) });
    await page.settle();
    fireEvent.click(screen.getByRole('button', { name: 'How the AI allowance works' }));
    expect(screen.getByText(/based on 5m observed/)).toBeVisible();
  });

  it('a window whose entry is an error publishes no row at all', async () => {
    const page = mountPanels(<CapacityStrip />, {
      data: board([entry('claude', { fiveH: window(30, 9000, 18000) }, { state: 'error' })]),
      strict: false,
    });
    await page.settle();
    expect(document.querySelector('[data-next-capacity]')).toBeNull();
  });
});

describe('model sub-limits', () => {
  it('hang under the weekly row only, keep a measured zero, and claim no clock', async () => {
    const page = mountPanels(<CapacityStrip />, {
      data: board([
        entry(
          'claude',
          { fiveH: window(30, 9000, 18000), week: window(40, 3 * 86400, 604800) },
          {
            models: [
              { label: 'Opus', pct: 0 },
              { label: 'Sonnet', pct: 71 },
              { label: '<img src=x onerror=alert(1)>', pct: 5 },
              { label: 'z'.repeat(80), pct: 9 },
              { label: 'Bad', pct: 4.5 },
            ],
          },
        ),
      ]),
      strict: false,
    });
    await page.settle();
    fireEvent.click(rowOf('claude:week'));
    fireEvent.click(screen.getByRole('button', { name: 'How the AI allowance works' }));
    expect(document.querySelectorAll('[data-next-capacity-models]')).toHaveLength(1);
    const line = document.querySelector('[data-next-capacity-models="claude:week"]') as HTMLElement;
    expect(line.textContent).toContain('Opus 0%');
    expect(line.textContent).toContain('Sonnet 71%');
    expect(line.textContent).toContain('no pace and no projected end');
    expect(line.textContent).not.toContain('Bad');
    expect(line.querySelector('img')).toBeNull();
    expect(line.textContent).toContain('<img src=x onerror=alert(1)>');
    expect([...line.querySelectorAll('b')].some((b) => (b.textContent ?? '').length === 40)).toBe(
      true,
    );
    expect(screen.getByRole('progressbar').getAttribute('aria-label')).toBe(
      'Claude Code weekly allowance used',
    );
  });
});
