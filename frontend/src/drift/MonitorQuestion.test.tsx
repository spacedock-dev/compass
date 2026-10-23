import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json, mountIntent, type RecordedRequest } from '../intent/testing';
import { board, mountSession, monitorLease, SESSION_HASH, text } from '../intent/panel.testing';

/* "Do you still want to monitor this session?" The server holds the clock: it publishes `confirm_by` from 20
   minutes after the monitor started, or after the last Yes, until 10 minutes later. The page counts down to
   that time, posts the answer, and clears the banner in every tab because the deadline is the server's. With
   no answer the monitor turns off with a note that says why. */

const switchButton = () =>
  document.querySelector('[data-next-cockpit-action="live-monitor"]') as HTMLButtonElement;
const banner = () => document.querySelector('[data-next-live-question]') as HTMLElement | null;
const button = (name: string) =>
  [...(banner()?.querySelectorAll('button') ?? [])].find(
    (node) => node.textContent === name,
  ) as HTMLButtonElement;
const note = () => text('[data-next-live-note]');
const cue = () => text('#next-cockpit-cue-status');

const receipt = (ok: boolean, state: Record<string, unknown>, why = '') =>
  json({ ok, reason: why, state });
/* The state at the moment the question opens: due now, open for 600 seconds more. */
const asking = (over: Record<string, unknown> = {}) =>
  monitorLease({ banner_due_at: 1100, deadline: 1700, confirm_by: 1700, now: 1120, ...over });

function leaseServer() {
  const server = {
    calls: [] as Record<string, unknown>[],
    next: null as ((request: RecordedRequest) => Response) | null,
    handler: (request: RecordedRequest): Response => {
      server.calls.push(request.body ?? {});
      return server.next ? server.next(request) : receipt(true, monitorLease());
    },
  };
  return server;
}
const actions = (server: ReturnType<typeof leaseServer>) =>
  server.calls.map((call) =>
    call['action'] === 'beat'
      ? `beat:${String(call['visible'])}`
      : call['action'] === 'confirm'
        ? `confirm:${String(call['answer'])}`
        : String(call['action']),
  );

async function monitoring(server = leaseServer()) {
  const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
  await page.settle();
  await act(async () => {
    fireEvent.click(switchButton());
  });
  await page.settle();
  return { page, server };
}
describe('the question', () => {
  it('is not drawn while the monitor is off, or on with no question open', async () => {
    const page = mountSession();
    await page.settle();
    expect(banner()).toBeNull();
    const { page: on } = await monitoring();
    expect(banner()).toBeNull();
    on.unmount();
  });

  it('appears when the server says the question is open, with the exact question, Yes, No and a countdown', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    expect(banner()).not.toBeNull();
    expect(text('[data-next-live-question] strong')).toBe(
      'Do you still want to monitor this session?',
    );
    expect(button('Yes')).toBeTruthy();
    expect(button('No')).toBeTruthy();
    expect(text('[data-next-live-question] [data-next-live-countdown]')).toMatch(/9m 40s/);
  });

  it('counts down on the clock the page holds, to the server’s deadline', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    await page.advance(60_000);
    expect(text('[data-next-live-countdown]')).toMatch(/8m 40s/);
    await page.advance(300_000);
    expect(text('[data-next-live-countdown]')).toMatch(/3m 40s/);
  });

  it('is announced, once, when it opens', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    expect(cue()).toMatch(/Do you still want to monitor this session\?/);
    expect(cue()).toMatch(/turns off in 9 minutes/);
  });

  it('is keyboard reachable: Yes and No are buttons in the tab order, and a press of either answers', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    for (const name of ['Yes', 'No']) {
      const control = button(name);
      expect(control.tagName).toBe('BUTTON');
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(document.activeElement).toBe(control);
    }
  });

  it('answers Yes with a confirm post, and the banner goes while the monitor stays on', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    server.next = () =>
      receipt(
        true,
        monitorLease({ confirm_by: null, started_at: 1130, banner_due_at: 2330, now: 1130 }),
      );
    await act(async () => {
      fireEvent.click(button('Yes'));
    });
    await page.settle();
    expect(server.calls.at(-1)).toMatchObject({
      action: 'confirm',
      answer: 'yes',
      tab_id: 'tab-a',
    });
    expect(banner()).toBeNull();
    expect(switchButton().getAttribute('aria-checked')).toBe('true');
    expect(note()).toBe('');
  });

  it('asks again after the next twenty minutes, from the server’s new clock', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    server.next = () =>
      receipt(
        true,
        monitorLease({ confirm_by: null, banner_due_at: 2330, deadline: 2930, now: 1130 }),
      );
    await act(async () => {
      fireEvent.click(button('Yes'));
    });
    await page.settle();
    expect(banner()).toBeNull();
    server.next = () =>
      receipt(true, asking({ banner_due_at: 2330, confirm_by: 2930, deadline: 2930, now: 2340 }));
    await page.advance(20_000);
    expect(banner()).not.toBeNull();
    expect(text('[data-next-live-countdown]')).toMatch(/9m/);
  });

  it('answers No with a confirm post, turns the monitor off and says it was at the reader’s answer', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    server.next = () =>
      receipt(
        true,
        monitorLease({
          on: false,
          confirm_by: null,
          last_end: { reason: 'declined', at: 1130 },
          now: 1130,
        }),
      );
    await act(async () => {
      fireEvent.click(button('No'));
    });
    await page.settle();
    expect(server.calls.at(-1)).toMatchObject({ action: 'confirm', answer: 'no' });
    expect(banner()).toBeNull();
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(note()).toMatch(/turned off at your answer/);
    await page.advance(60_000);
    expect(actions(server).filter((a) => a.startsWith('beat'))).toHaveLength(1);
  });

  it('turns the monitor off with the unanswered note when the deadline passes with no answer, and beats no more', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    await page.advance(590_000);
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(banner()).toBeNull();
    expect(note()).toBe(
      'Live monitor turned off: no answer after 10 minutes, so no more model calls were made.',
    );
    const beats = actions(server).filter((a) => a.startsWith('beat')).length;
    await page.advance(120_000);
    expect(actions(server).filter((a) => a.startsWith('beat'))).toHaveLength(beats);
  });

  it('clears and shows the reason’s note, not the unanswered one, when the lease ends another way while it is up', async () => {
    for (const [reason, pattern] of [
      ['left', /left the session/],
      ['ended', /session ended/],
      ['paused', /model calls are paused/],
    ] as const) {
      const { page, server } = await monitoring();
      server.next = () => receipt(true, asking());
      await page.advance(20_000);
      expect(banner()).not.toBeNull();
      server.next = () =>
        receipt(
          false,
          monitorLease({ on: false, confirm_by: null, last_end: { reason, at: 1300 }, now: 1300 }),
          'not-monitoring',
        );
      await page.advance(20_000);
      expect(banner()).toBeNull();
      expect(note()).toMatch(pattern);
      expect(note()).not.toMatch(/no answer after/);
      page.unmount();
    }
  });

  it('clears in this tab when another tab answered, because the next state has no question', async () => {
    const { page, server } = await monitoring();
    server.next = () => receipt(true, asking());
    await page.advance(20_000);
    expect(banner()).not.toBeNull();
    server.next = () =>
      receipt(
        true,
        monitorLease({ confirm_by: null, started_at: 1140, banner_due_at: 2340, now: 1140 }),
      );
    await page.advance(20_000);
    expect(banner()).toBeNull();
    expect(switchButton().getAttribute('aria-checked')).toBe('true');
  });

  it('is never drawn for another harness', async () => {
    const codex = mountIntent({
      hash: '#n=session:alpha%2Fapp:codex:c1',
      data: board({ harness: 'codex', sid: 'c1' }),
    });
    await codex.settle();
    expect(banner()).toBeNull();
    expect(SESSION_HASH).toContain('claude');
  });
});
