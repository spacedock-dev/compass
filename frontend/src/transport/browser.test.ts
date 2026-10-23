import { describe, expect, it, vi } from 'vitest';
import { blockedBackend } from '../../test/storage_backends';
import type { FetchLike } from '../api/client';
import { createBrowserEnvironment, createBrowserRuntime, type BrowserGlobals } from './browser';
import { createFakeClock, createFakeEnvironment } from './testing';

function globals(options: { hidden?: boolean; withEventSource?: boolean } = {}) {
  const windowListeners = new Map<string, Set<() => void>>();
  const documentListeners = new Map<string, Set<() => void>>();
  const track = (map: Map<string, Set<() => void>>) => ({
    addEventListener: (type: string, listener: () => void) =>
      void (map.get(type) ?? map.set(type, new Set()).get(type))?.add(listener),
    removeEventListener: (type: string, listener: () => void) =>
      void map.get(type)?.delete(listener),
  });
  const opened: string[] = [];
  class FakeSource {
    readyState = 0;
    constructor(readonly url: string) {
      opened.push(url);
    }
    close() {
      this.readyState = 2;
    }
    addEventListener() {
      /* unused here */
    }
  }
  const state = { hidden: options.hidden ?? false };
  const g: BrowserGlobals = {
    window: {
      ...track(windowListeners),
      setTimeout: vi.fn(),
      clearTimeout: vi.fn(),
      setInterval: vi.fn(),
      clearInterval: vi.fn(),
    },
    document: {
      ...track(documentListeners),
      get hidden() {
        return state.hidden;
      },
    },
    EventSource:
      options.withEventSource === false
        ? undefined
        : (FakeSource as unknown as BrowserGlobals['EventSource']),
    now: () => 4242,
  };
  const count = (map: Map<string, Set<() => void>>, type: string) => map.get(type)?.size ?? 0;
  return {
    g,
    state,
    opened,
    windowListeners,
    documentListeners,
    fire: (map: Map<string, Set<() => void>>, type: string) => {
      for (const listener of [...(map.get(type) ?? [])]) listener();
    },
    count,
  };
}

describe('browser environment', () => {
  it('names the tab with the released random-and-timestamp shape', () => {
    const env = createBrowserEnvironment(globals().g);
    expect(env.tabId).toMatch(/^[a-z0-9]+-4242$/);
  });

  it('opens the stream route and reports support from the constructor’s presence', () => {
    const supported = globals();
    const env = createBrowserEnvironment(supported.g);
    expect(env.streamSupported).toBe(true);
    env.openStream();
    expect(supported.opened).toEqual(['/api/stream']);
    expect(createBrowserEnvironment(globals({ withEventSource: false }).g).streamSupported).toBe(
      false,
    );
  });

  it('adds and removes its pagehide listener', () => {
    const t = globals();
    const env = createBrowserEnvironment(t.g);
    const off = env.onPageHide(() => undefined);
    expect(t.count(t.windowListeners, 'pagehide')).toBe(1);
    off();
    expect(t.count(t.windowListeners, 'pagehide')).toBe(0);
  });

  it('reports a visibility change only when the page is visible', () => {
    const t = globals({ hidden: true });
    const env = createBrowserEnvironment(t.g);
    const seen = vi.fn();
    const off = env.onBecameVisible(seen);
    t.fire(t.documentListeners, 'visibilitychange');
    expect(seen).not.toHaveBeenCalled();
    t.state.hidden = false;
    t.fire(t.documentListeners, 'visibilitychange');
    expect(seen).toHaveBeenCalledOnce();
    off();
    expect(t.count(t.documentListeners, 'visibilitychange')).toBe(0);
  });

  it('reports a visibility change only when the page has become hidden', () => {
    const t = globals({ hidden: false });
    const env = createBrowserEnvironment(t.g);
    const seen = vi.fn();
    const off = env.onBecameHidden(seen);
    t.fire(t.documentListeners, 'visibilitychange');
    expect(seen).not.toHaveBeenCalled();
    t.state.hidden = true;
    t.fire(t.documentListeners, 'visibilitychange');
    expect(seen).toHaveBeenCalledOnce();
    off();
    expect(t.count(t.documentListeners, 'visibilitychange')).toBe(0);
  });

  it('sends a beacon of JSON where the browser has one, and says so where it has none', () => {
    const sent: { url: string; body: unknown }[] = [];
    const t = globals();
    const withBeacon = createBrowserEnvironment({
      ...t.g,
      sendBeacon: (url, body) => {
        sent.push({ url, body });
        return true;
      },
    });
    expect(withBeacon.sendBeacon('/api/live-monitor', '{"a":1}')).toBe(true);
    expect(sent).toHaveLength(1);
    expect(sent[0]?.url).toBe('/api/live-monitor');
    expect((sent[0]?.body as Blob).type).toBe('application/json');
    expect(createBrowserEnvironment(t.g).sendBeacon('/api/live-monitor', '{}')).toBe(false);
    const refusing = createBrowserEnvironment({ ...t.g, sendBeacon: () => false });
    expect(refusing.sendBeacon('/api/live-monitor', '{}')).toBe(false);
  });

  it('delegates timers to the window and time to the supplied clock', () => {
    const t = globals();
    const env = createBrowserEnvironment(t.g);
    expect(env.clock.now()).toBe(4242);
    const callback = vi.fn();
    env.clock.setTimeout(callback, 5);
    env.clock.setInterval(callback, 7);
    expect(t.g.window.setTimeout).toHaveBeenCalledWith(callback, 5);
    expect(t.g.window.setInterval).toHaveBeenCalledWith(callback, 7);
  });
});

describe('the browser runtime shares one storage instance', () => {
  const flush = async () => {
    for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
  };

  function blockedRuntime() {
    const urls: string[] = [];
    const fetch: FetchLike = (url) => {
      urls.push(url);
      const body = url.startsWith('/api/project-context')
        ? { observer_model: { enabled: true, disclosure: 'Sends prose to a model.' } }
        : { generated: 1, sessions: [] };
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    };
    const runtime = createBrowserRuntime({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      fetch,
      provider: () => blockedBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
    });
    return { runtime, urls };
  }

  it('lets a quota grant made through the runtime’s storage ungate usage when browser storage is blocked', async () => {
    const { runtime, urls } = blockedRuntime();
    runtime.storage.usageConsent.set('granted');
    runtime.start();
    await flush();
    expect(urls[0]).toBe('/api/data?usage=1');
    runtime.dispose();
  });

  it('runs the explicit summary unanswered, and keeps a decline stored in the runtime’s storage', async () => {
    const { runtime, urls } = blockedRuntime();
    runtime.start();
    await flush();
    const scope = { projectKey: 'p', focus: { harness: 'claude', sid: 's' } };
    runtime.loadContext(scope);
    await flush();
    await runtime.requestObserverSummary(scope);
    expect(urls.filter((url) => url.includes('observer_model=1'))).toHaveLength(1);
    runtime.storage.observerConsent.set('declined');
    await runtime.requestObserverSummary(scope);
    expect(urls.filter((url) => url.includes('refresh=1&observer_model=1'))).toHaveLength(1);
    runtime.dispose();
  });
});

/* The page's shell owns the live regions and the held paint, so the browser runtime hands its hooks
   through to the board runtime rather than leaving the shell to rebuild the runtime around them. */
describe('the browser runtime hands the shell its announce, forget and paint hooks through', () => {
  const flush = async () => {
    for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
  };

  it('says a slow pending start sentence once, forgets it when the entry ends, and reports each paint', async () => {
    const clock = createFakeClock();
    const announce = vi.fn();
    const forget = vi.fn();
    const paint = vi.fn(() => Promise.resolve());
    const runtime = createBrowserRuntime({
      env: createFakeEnvironment({ clock }),
      fetch: () =>
        Promise.resolve(
          new Response(JSON.stringify({ generated: 1, sessions: [] }), { status: 200 }),
        ),
      provider: () => blockedBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      announce,
      forget,
      paint,
    });
    runtime.start();
    await flush();
    expect(paint).toHaveBeenCalledWith({ manual: false, accepted: true });

    const token = runtime.pending.start('save:a', 'Saving', 'Saving the line.');
    clock.advance(400);
    expect(announce).toHaveBeenCalledOnce();
    expect(announce).toHaveBeenCalledWith('save:a', 'Saving the line.');
    expect(forget).not.toHaveBeenCalled();
    runtime.pending.end('save:a', token);
    expect(forget).toHaveBeenCalledWith('save:a');
    runtime.dispose();
  });
});
