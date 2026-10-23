import type { FetchLike } from '../api/client';
import {
  createLegacyStorage,
  createTabId,
  type BackendProvider,
  type LegacyStorage,
} from '../storage';
import { createTransportStorage, type StorageEventTarget } from './legacyStorage';
import type { Environment, EventSourceLike, TimerHandle } from './ports';
import { createBoardRuntime, type BoardRuntime, type RuntimeOptions } from './runtime';

/* The browser surface the environment reads, named so a test can supply it
   without a real window. */
export interface BrowserGlobals {
  readonly window: {
    addEventListener(type: string, listener: () => void): void;
    removeEventListener(type: string, listener: () => void): void;
    setTimeout(callback: () => void, ms: number): TimerHandle;
    clearTimeout(handle: TimerHandle): void;
    setInterval(callback: () => void, ms: number): TimerHandle;
    clearInterval(handle: TimerHandle): void;
  };
  readonly document: {
    addEventListener(type: string, listener: () => void): void;
    removeEventListener(type: string, listener: () => void): void;
    readonly hidden: boolean;
  };
  readonly EventSource: (new (url: string) => EventSourceLike) | undefined;
  readonly now: () => number;
  /** `navigator.sendBeacon`, where the browser has it. */
  readonly sendBeacon?: (url: string, body: Blob) => boolean;
}

export function createBrowserEnvironment(g: BrowserGlobals): Environment {
  const listen = (
    target: Pick<BrowserGlobals['window'], 'addEventListener' | 'removeEventListener'>,
    type: string,
    listener: () => void,
  ) => {
    target.addEventListener(type, listener);
    return () => target.removeEventListener(type, listener);
  };
  const Source = g.EventSource;
  return {
    tabId: createTabId(Math.random, g.now()),
    clock: {
      now: g.now,
      setTimeout: (callback, ms) => g.window.setTimeout(callback, ms),
      clearTimeout: (handle) => g.window.clearTimeout(handle),
      setInterval: (callback, ms) => g.window.setInterval(callback, ms),
      clearInterval: (handle) => g.window.clearInterval(handle),
    },
    streamSupported: Source !== undefined,
    openStream() {
      if (!Source) throw new Error('EventSource is not available');
      return new Source('/api/stream');
    },
    onPageHide: (listener) => listen(g.window, 'pagehide', listener),
    onBecameVisible: (listener) =>
      listen(g.document, 'visibilitychange', () => {
        if (!g.document.hidden) listener();
      }),
    isHidden: () => g.document.hidden,
    onBecameHidden: (listener) =>
      listen(g.document, 'visibilitychange', () => {
        if (g.document.hidden) listener();
      }),
    sendBeacon(url, body) {
      if (!g.sendBeacon) return false;
      try {
        return g.sendBeacon(url, new Blob([body], { type: 'application/json' }));
      } catch {
        return false;
      }
    },
  };
}

/* `navigator.sendBeacon`, where this browser has it, as the one optional global the environment takes. */
export function browserBeacon(): Pick<BrowserGlobals, 'sendBeacon'> {
  return typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function'
    ? { sendBeacon: (url: string, body: Blob) => navigator.sendBeacon(url, body) }
    : {};
}

export type BrowserRuntime = BoardRuntime & {
  /** The document's one storage instance, shared with the UI so in-tab consent and memo fallbacks agree when browser storage is blocked. */
  readonly storage: LegacyStorage;
};

export interface BrowserRuntimeOptions {
  readonly env?: Environment;
  readonly fetch?: FetchLike;
  readonly provider?: BackendProvider;
  readonly events?: StorageEventTarget;
  readonly search?: string;
  readonly doc?: Pick<Document, 'querySelector'> | null;
  /* The shell's hooks, passed through to the board runtime untouched: where a paint is held back, and
     where a pending control's start sentence is spoken and forgotten. */
  readonly paint?: RuntimeOptions['paint'];
  readonly announce?: RuntimeOptions['announce'];
  readonly forget?: RuntimeOptions['forget'];
}

/* Builds the runtime for this document and starts nothing: the caller decides
   when (an effect's `acquire`). The one `LegacyStorage` it creates is exposed,
   because each instance holds its own in-tab fallbacks and a second instance
   would disagree with the transport about consent when storage is blocked. The
   options exist for tests; production passes none. */
export function createBrowserRuntime(options: BrowserRuntimeOptions = {}): BrowserRuntime {
  const globals: BrowserGlobals = {
    window,
    document,
    EventSource:
      typeof EventSource === 'undefined'
        ? undefined
        : (EventSource as unknown as new (
            url: string,
          ) => EventSourceLike),
    now: () => Date.now(),
    ...browserBeacon(),
  };
  const legacy = options.provider ? createLegacyStorage(options.provider) : createLegacyStorage();
  const runtime = createBoardRuntime({
    fetch: options.fetch ?? ((url, init) => fetch(url, init)),
    storage: createTransportStorage(legacy, options.events ?? window),
    env: options.env ?? createBrowserEnvironment(globals),
    search: options.search ?? window.location.search,
    doc: options.doc === undefined ? document : options.doc,
    ...(options.paint ? { paint: options.paint } : {}),
    ...(options.announce ? { announce: options.announce } : {}),
    ...(options.forget ? { forget: options.forget } : {}),
  });
  return Object.assign(runtime, { storage: legacy });
}
