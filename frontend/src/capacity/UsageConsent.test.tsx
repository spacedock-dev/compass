import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mountPanels, type MountOptions } from '../steering/testing';
import { CapacityStrip } from './CapacityStrip';
import { heldFor, useConsent } from './held';
import { CapacityPanel } from '../delegation/CapacityPanel';
import { observe } from '../observed';
import { RailUsage } from './UsageConsent';

/* Usage fetching is on until the reader turns it off, and what the reader chose is what the next request
   says. The request is read where it is made: every `/api/data` URL the page sent is counted, because the
   failure that matters is a request the reader turned off. Nothing here reads a credential: the backend is a
   script that answers from a board. */
const CONSENT = 'compass.next.usage.consent';
const board = (over: Record<string, unknown> = {}) => ({
  generated: 1000,
  usage_fetch: true,
  harnesses: [{ key: 'claude', label: 'Claude Code' }],
  usage: [
    {
      harness: 'claude',
      state: 'ok',
      asOf: 990,
      fiveH: { pct: 34, windowSec: 18000, resetAt: 1000 + 9000 },
    },
  ],
  sessions: [],
  ...over,
});
const mount = (options: MountOptions = {}, strip = true) =>
  mountPanels(strip ? <CapacityStrip /> : <RailUsage windows />, { data: board(), ...options });
/* The Console rail: the switch sits under the capacity panel, which is told the recorded switch as
   `ProjectConsole` tells it, and is told whether that panel drew a window or hid one. */
function Rail({ payload }: { readonly payload: ReturnType<typeof board> }) {
  const quotaOff = useConsent('usage') === 'declined';
  return (
    <CapacityPanel
      payload={payload}
      model={observe(payload)}
      quotaOff={quotaOff}
      usage={(windows, hidden) => <RailUsage windows={windows} hidden={hidden} />}
    />
  );
}
const rail = (payload: ReturnType<typeof board>) => <Rail payload={payload} />;
const dataUrls = (page: ReturnType<typeof mount>): string[] =>
  page.state.requests.filter((r) => r.path === '/api/data').map((r) => r.url);
const withUsage = (page: ReturnType<typeof mount>): string[] =>
  dataUrls(page).filter((url) => /[?&]usage=/.test(url));
const press = (answer: string) => {
  const button = document.querySelector(`[data-next-usage-answer="${answer}"]`);
  if (!button) throw new Error(`no ${answer} button`);
  fireEvent.click(button);
};

const line = () => document.querySelector('[data-next-usage-switch]');

describe('the quota fetch is on until it is turned off', () => {
  it('says what is read and that no session content is sent, and asks for usage on mount', async () => {
    const page = mount();
    await page.settle();
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('on');
    expect(line()?.textContent).toContain(
      'Quota is read with the Claude Code and Cursor logins on this machine. No session content is sent.',
    );
    expect(line()?.querySelector('button')?.textContent).toBe('Turn off quota reading');
    expect(dataUrls(page).length).toBeGreaterThan(0);
    expect(dataUrls(page).every((url) => /[?&]usage=1(&|$)/.test(url))).toBe(true);
    expect(document.querySelector('[data-next-usage-consent]')).toBeNull();
  });

  it('an unrecognised stored answer reads as on', async () => {
    const page = mount({ storage: { [CONSENT]: 'yes' } });
    await page.settle();
    expect(dataUrls(page)[0]).toMatch(/usage=1/);
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('on');
  });

  it('declined sends none, however long it runs, and keeps the choice to change it', async () => {
    const page = mount({ storage: { [CONSENT]: 'declined' } });
    await page.settle();
    await page.poll(board({ generated: 1001 }));
    await page.advance(120_000);
    expect(dataUrls(page).length).toBeGreaterThan(1);
    expect(withUsage(page)).toEqual([]);
    expect(line()?.textContent).toContain('Quota reading is off. The last cached read will lapse.');
    expect(line()?.querySelector('button')?.textContent).toBe('Turn on quota reading');
  });

  it('declined with no window published does not describe a cached read', async () => {
    const page = mount({ storage: { [CONSENT]: 'declined' }, data: board({ usage: [] }) });
    await page.settle();
    expect(line()?.textContent).toContain('Quota reading is off. No window has been read.');
    expect(line()?.textContent).not.toContain('last cached read');
    expect(line()?.querySelector('button')?.textContent).toBe('Turn on quota reading');
  });

  it('names a cached credential window without displaying its figures', async () => {
    const page = mount({ storage: { [CONSENT]: 'declined' } });
    await page.settle();
    expect(line()?.textContent).toContain('Quota reading is off. The last cached read will lapse.');
    expect(document.querySelector('[data-next-capacity]')?.textContent).toContain(
      'Last cached window: Claude Code 5-hour',
    );
    expect(document.querySelector('progress')).toBeNull();
  });

  it('the Console rail, declined with no window published, does not describe a cached read', async () => {
    const empty = board({ usage: [] });
    const page = mountPanels(rail(empty), { data: empty, storage: { [CONSENT]: 'declined' } });
    await page.settle();
    expect(line()?.textContent).toContain('Quota reading is off. No window has been read.');
    expect(line()?.textContent).not.toContain('last cached read');
    expect(line()?.querySelector('button')?.textContent).toBe('Turn on quota reading');
  });

  it('the Console rail, declined with a Claude window read, hides it and says the read will lapse', async () => {
    const full = board();
    const page = mountPanels(rail(full), { data: full, storage: { [CONSENT]: 'declined' } });
    await page.settle();
    expect(line()?.textContent).toContain('Quota reading is off. The last cached read will lapse.');
    expect(document.querySelector('[data-next-rail-window]')).toBeNull();
  });

  it('the Console rail, declined beside a Codex reading, keeps Codex and says local readings stay', async () => {
    const both = board({
      usage: [
        ...board().usage,
        { harness: 'codex', state: 'ok', fiveH: { pct: 71, windowSec: 10800, resetAt: 9000 } },
      ],
    });
    const page = mountPanels(rail(both), { data: both, storage: { [CONSENT]: 'declined' } });
    await page.settle();
    const rows = document.querySelectorAll('[data-next-rail-window]');
    expect(rows).toHaveLength(1);
    expect(rows[0]?.textContent).toContain('71%');
    expect(line()?.textContent).toContain(
      'Quota reading is off for Claude Code and Cursor. Local readings are still shown.',
    );
  });

  it('Turn off stops the parameter at once and is remembered', async () => {
    const page = mount();
    await page.settle();
    const before = dataUrls(page).length;
    press('declined');
    await page.settle();
    await page.poll(board({ generated: 1005 }));
    const after = dataUrls(page).slice(before);
    expect(after.length).toBeGreaterThanOrEqual(1);
    expect(after.some((url) => /usage=/.test(url))).toBe(false);
    expect(page.backend.data.get(CONSENT)).toBe('declined');
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('off');
  });

  it('Turn on sends usage=1 on the next request', async () => {
    const page = mount({ storage: { [CONSENT]: 'declined' } });
    await page.settle();
    const before = dataUrls(page).length;
    press('granted');
    await page.settle();
    const after = dataUrls(page).slice(before);
    expect(after.length).toBeGreaterThanOrEqual(1);
    expect(after.every((url) => /[?&]usage=1(&|$)/.test(url))).toBe(true);
    expect(page.backend.data.get(CONSENT)).toBe('granted');
  });

  it('offers nothing and asks for nothing unless the server raised the flag with a real true', async () => {
    for (const flag of [undefined, false, 'yes', 1, null]) {
      const page = mount({ data: board({ usage_fetch: flag }) });
      await page.settle();
      expect(line(), `flag ${String(flag)}`).toBeNull();
      page.unmount();
    }
  });

  it('the line stands alone with no window published', async () => {
    const page = mount({ data: board({ usage: [] }) });
    await page.settle();
    expect(line()).not.toBeNull();
    expect(document.querySelector('progress')).toBeNull();
  });
});

describe('the answer survives what browsers do to storage', () => {
  const refuseWrites = (page: ReturnType<typeof mount>) => {
    (page.backend as { setItem: unknown }).setItem = () => {
      throw new DOMException('quota', 'QuotaExceededError');
    };
  };

  it('a profile that refuses the write keeps Turn off for this tab, and the fetch follows it', async () => {
    const page = mount();
    await page.settle();
    refuseWrites(page);
    const before = dataUrls(page).length;
    press('declined');
    await page.settle();
    expect(page.backend.data.has(CONSENT)).toBe(false);
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('off');
    expect(dataUrls(page).length).toBeGreaterThan(before);
    expect(
      dataUrls(page)
        .slice(before)
        .some((url) => /usage=/.test(url)),
    ).toBe(false);
  });

  it("another tab's Turn off changes this tab's line without a press", async () => {
    const page = mount();
    await page.settle();
    page.backend.data.set(CONSENT, 'declined');
    await act(async () => {
      window.dispatchEvent(new StorageEvent('storage', { key: CONSENT, newValue: 'declined' }));
    });
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('off');
  });
});

describe('the rail draws the same line', () => {
  it('shows the line and switches it, with the same request behaviour', async () => {
    const page = mount({}, false);
    await page.settle();
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('on');
    expect(dataUrls(page).at(-1)).toMatch(/usage=1/);
    press('declined');
    await page.settle();
    expect(line()?.getAttribute('data-next-usage-switch')).toBe('off');
  });

  it('keyboard focus stays on the switch across a press', async () => {
    const page = mount({}, false);
    await page.settle();
    const button = document.querySelector<HTMLElement>('.next-usage-switch button');
    button?.focus();
    press('declined');
    await page.settle();
    expect(document.activeElement).toBe(document.querySelector('.next-usage-switch button'));
  });
});

describe('what is held between draws', () => {
  it('the consent lane reads the same storage the transport reads', async () => {
    const page = mount({ storage: { [CONSENT]: 'granted' } });
    await page.settle();
    expect(heldFor(page.shell.runtime).usage.read()).toBe('granted');
  });
});
