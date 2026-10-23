import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json, mountIntent, type RecordedRequest } from './testing';
import { board, mountSession, SESSION_HASH, text } from './panel.testing';

/* The Live monitor switch drives a lease the server holds. Pressing it starts the lease and beats it while
   the session is on screen and the tab is visible; leaving the route, switching session or hiding the tab
   stops the beats, and a reload starts with the switch off. What the server says about the lease, not a
   key in this browser, decides whether it is on. */

const switchButton = () =>
  document.querySelector('[data-next-cockpit-action="live-monitor"]') as HTMLButtonElement;
const note = () => text('[data-next-live-note]');
const reason = () => text('[data-next-live-reason]');

const lease = (over: Record<string, unknown> = {}) => ({
  on: true,
  started_at: 1000,
  banner_due_at: 2200,
  deadline: 2800,
  confirm_by: null,
  visible: true,
  last_end: null,
  level: null,
  label: 'Live monitor · Haiku',
  model: 'claude-haiku-5-5',
  destination: 'api.anthropic.com',
  disclosure: 'Sends to api.anthropic.com through your Claude Code, to Haiku.',
  interval_sec: 60,
  now: 1100,
  ...over,
});
const receipt = (ok: boolean, state: Record<string, unknown>, why = '') =>
  json({ ok, reason: why, state });

/* A server that holds one lease: start and beats keep it on, and a test can end it. */
function leaseServer() {
  const server = {
    calls: [] as Record<string, unknown>[],
    next: null as ((request: RecordedRequest) => Response) | null,
    handler: (request: RecordedRequest): Response => {
      server.calls.push(request.body ?? {});
      return server.next ? server.next(request) : receipt(true, lease());
    },
  };
  return server;
}
const actions = (server: ReturnType<typeof leaseServer>) =>
  server.calls.map((call) =>
    call['action'] === 'beat' ? `beat:${String(call['visible'])}` : String(call['action']),
  );

const press = async (page: ReturnType<typeof mountSession>) => {
  await act(async () => {
    fireEvent.click(switchButton());
  });
  await page.settle();
};

describe('the live monitor switch', () => {
  it('is off by default, drawn beside the Drift heading, and drawing it sends nothing', async () => {
    const page = mountSession();
    await page.settle();
    expect(switchButton().getAttribute('role')).toBe('switch');
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(text('#next-session-drift-monitor-label')).toBe('Live monitor');
    expect(page.posts()).toBe(0);
  });

  it('names the model call, the cadence and the provider in its hint', async () => {
    const page = mountSession();
    await page.settle();
    const hint = text('[data-next-live-hint]');
    expect(hint).toMatch(/Haiku/);
    expect(hint).toMatch(/about once a minute/);
    expect(hint).toMatch(/Claude Code/);
    expect(hint).not.toMatch(/no model call/);
  });

  it('starts a lease when turned on, with this tab’s id, then beats it every twenty seconds', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    expect(switchButton().getAttribute('aria-checked')).toBe('true');
    expect(server.calls[0]).toEqual({
      harness: 'claude',
      sid: 's1',
      action: 'start',
      tab_id: 'tab-a',
      observer_model: 1,
    });
    await page.advance(20_000);
    await page.advance(20_000);
    expect(actions(server)).toEqual(['start', 'beat:true', 'beat:true']);
    expect(server.calls[1]).toMatchObject({ harness: 'claude', sid: 's1', tab_id: 'tab-a' });
  });

  it('stops beating while the tab is hidden, says so once, and resumes when it is shown', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    await act(async () => {
      page.env.fireHidden();
    });
    await page.settle();
    await page.advance(120_000);
    expect(actions(server)).toEqual(['start', 'beat:false']);
    await act(async () => {
      page.env.fireVisible();
    });
    await page.settle();
    await page.advance(20_000);
    expect(actions(server)).toEqual(['start', 'beat:false', 'beat:true', 'beat:true']);
  });

  it('posts stop when the reader turns it off, and beats no more', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    await press(page);
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start', 'stop']);
    expect(note()).toBe('');
  });

  it('posts stop when the reader leaves the route, and finds it off on coming back', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    await page.go('#n=intent');
    expect(actions(server)).toEqual(['start', 'stop']);
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start', 'stop']);
    await page.go(SESSION_HASH);
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start', 'stop']);
  });

  it('posts stop for the first session when the reader moves to another, and does not start the second', async () => {
    const server = leaseServer();
    const data = board();
    const first = data.sessions[0] as Record<string, unknown>;
    const page = mountIntent({
      hash: SESSION_HASH,
      data: { ...data, sessions: [first, { ...first, sid: 's2', title: 'Beta work' }] },
      routes: { '/api/live-monitor': server.handler },
    });
    await page.settle();
    await press(page as never);
    await page.go('#n=session:alpha%2Fapp:claude:s2');
    expect(actions(server)).toEqual(['start', 'stop']);
    expect(server.calls[1]).toMatchObject({ sid: 's1' });
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start', 'stop']);
  });

  it('sends a stop beacon as the page goes away, which the server does not depend on', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    await act(async () => {
      page.env.firePageHide();
    });
    expect(page.env.beacons).toHaveLength(1);
    expect(page.env.beacons[0]?.url).toBe('/api/live-monitor');
    expect(JSON.parse(page.env.beacons[0]?.body ?? '{}')).toEqual({
      harness: 'claude',
      sid: 's1',
      action: 'stop',
      tab_id: 'tab-a',
    });
  });

  it('shows the switch off after a reload, until it is pressed', async () => {
    const server = leaseServer();
    const first = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await first.settle();
    await press(first);
    expect(switchButton().getAttribute('aria-checked')).toBe('true');
    first.unmount();
    const second = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await second.settle();
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(second.posts()).toBe(0);
  });

  it('turns back off, with the reason, when the server refuses to start', async () => {
    const server = leaseServer();
    server.next = () => receipt(false, lease({ on: false }), 'paused');
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(note()).toMatch(/did not start.*paused/);
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start']);
  });

  it('turns off, with a note, when a beat finds the lease gone', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    server.next = () =>
      receipt(
        false,
        lease({ on: false, last_end: { reason: 'left', at: 1200 } }),
        'not-monitoring',
      );
    await page.advance(20_000);
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(note()).toMatch(/left the session/);
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start', 'beat:true']);
  });

  it('is drawn only for Claude Code with annotations on, and sends nothing for any other', async () => {
    const server = leaseServer();
    const codex = mountIntent({
      hash: '#n=session:alpha%2Fapp:codex:c1',
      data: board({ harness: 'codex', sid: 'c1' }),
      routes: { '/api/live-monitor': server.handler },
    });
    await codex.settle();
    expect(document.querySelector('[data-next-cockpit-action="live-monitor"]')).toBeNull();
    codex.unmount();
    const off = mountIntent({ hash: SESSION_HASH, data: { ...board(), annotate: false } });
    await off.settle();
    expect(document.querySelector('[data-next-cockpit-action="live-monitor"]')).toBeNull();
    expect(server.calls).toEqual([]);
  });
});

describe('the switch when there is nothing live to monitor', () => {
  it('is disabled, with its reason, for a session that has ended, and a press sends nothing', async () => {
    const server = leaseServer();
    const page = mountSession({
      session: { ended_at: 500 },
      routes: { '/api/live-monitor': server.handler },
    });
    await page.settle();
    expect(switchButton().getAttribute('aria-disabled')).toBe('true');
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(reason()).toBe('The session has ended');
    await act(async () => {
      fireEvent.click(switchButton());
    });
    await page.settle();
    expect(server.calls).toEqual([]);
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
  });

  it('flips to off and disabled, with the session-ended note, when the session ends while it is viewed', async () => {
    const server = leaseServer();
    const page = mountSession({ routes: { '/api/live-monitor': server.handler } });
    await page.settle();
    await press(page);
    expect(switchButton().getAttribute('aria-checked')).toBe('true');
    await page.poll(board({ ended_at: 1200 }));
    expect(switchButton().getAttribute('aria-checked')).toBe('false');
    expect(switchButton().getAttribute('aria-disabled')).toBe('true');
    expect(note()).toMatch(/session ended/);
    expect(reason()).toBe('The session has ended');
    await page.advance(60_000);
    expect(actions(server)).toEqual(['start', 'stop']);
  });

  it('is disabled, with its reason, while model calls are paused', async () => {
    const page = mountSession({ session: {} });
    await page.settle();
    page.unmount();
    const paused = mountIntent({
      hash: SESSION_HASH,
      data: { ...board(), reading: { off: true, reason: 'model-calls-paused' } },
    });
    await paused.settle();
    expect(switchButton().getAttribute('aria-disabled')).toBe('true');
    expect(reason()).toBe('Model calls are paused');
  });

  it('is disabled, with its reason, when model calls are off for the run', async () => {
    const off = mountIntent({
      hash: SESSION_HASH,
      data: { ...board(), reading: { off: false, reason: 'run-disabled' } },
    });
    await off.settle();
    expect(switchButton().getAttribute('aria-disabled')).toBe('true');
    expect(reason()).toBe('Model calls are off for this run');
  });
});
