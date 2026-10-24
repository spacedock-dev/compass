/* Test doubles for the transport ports. Not imported by production code. */
import type {
  Clock,
  Consent,
  ConsentAnswer,
  Environment,
  EventSourceLike,
  Lease,
  TimerHandle,
  TransportStorage,
} from './ports';

interface FakeTimer {
  readonly id: number;
  at: number;
  readonly every: number | null;
  readonly callback: () => void;
}

export interface FakeClock extends Clock {
  advance(ms: number): void;
  activeTimers(): number;
}

export function createFakeClock(start = 1_000_000): FakeClock {
  let now = start;
  let nextId = 1;
  let timers: FakeTimer[] = [];
  const schedule = (callback: () => void, ms: number, every: number | null): TimerHandle => {
    const timer: FakeTimer = { id: nextId++, at: now + ms, every, callback };
    timers.push(timer);
    return timer.id;
  };
  const cancel = (handle: TimerHandle) => {
    timers = timers.filter((timer) => timer.id !== handle);
  };
  return {
    now: () => now,
    setTimeout: (callback, ms) => schedule(callback, ms, null),
    clearTimeout: cancel,
    setInterval: (callback, ms) => schedule(callback, ms, ms),
    clearInterval: cancel,
    activeTimers: () => timers.length,
    advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = timers
          .filter((timer) => timer.at <= target)
          .sort((a, b) => a.at - b.at || a.id - b.id)[0];
        if (!due) break;
        now = due.at;
        if (due.every === null) cancel(due.id);
        else due.at += due.every;
        due.callback();
      }
      now = target;
    },
  };
}

export class FakeEventSource implements EventSourceLike {
  readyState = 0;
  closed = false;
  private readonly listeners = new Map<string, ((event: { readonly data?: unknown }) => void)[]>();

  addEventListener(
    type: 'error' | 'revision',
    listener: (event: { readonly data?: unknown }) => void,
  ): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }

  emit(type: 'error' | 'revision', data?: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener({ data });
  }

  /** The browser's behaviour: CONNECTING keeps retrying, CLOSED does not. */
  fail(readyState: 0 | 2): void {
    this.readyState = readyState;
    this.emit('error');
  }
}

export interface FakeEnvironment extends Environment {
  readonly clock: FakeClock;
  readonly sources: FakeEventSource[];
  streamOpens(): number;
  openStreams(): number;
  listenerCount(): number;
  firePageHide(): void;
  fireVisible(): void;
  fireHidden(): void;
  /** Whether the tab is hidden now, as `fireHidden` and `fireVisible` leave it. */
  hidden: boolean;
  /** Every beacon sent, in order. */
  readonly beacons: { readonly url: string; readonly body: string }[];
  throwOnOpen: boolean;
}

export function createFakeEnvironment(
  options: {
    readonly clock?: FakeClock;
    readonly tabId?: string;
    readonly streamSupported?: boolean;
  } = {},
): FakeEnvironment {
  const clock = options.clock ?? createFakeClock();
  const pageHide = new Set<() => void>();
  const visible = new Set<() => void>();
  const hidden = new Set<() => void>();
  const tab = { hidden: false };
  const beacons: { url: string; body: string }[] = [];
  const sources: FakeEventSource[] = [];
  const environment: FakeEnvironment = {
    tabId: options.tabId ?? 'tab-a',
    clock,
    streamSupported: options.streamSupported ?? true,
    sources,
    throwOnOpen: false,
    openStream() {
      if (environment.throwOnOpen) throw new Error('EventSource refused');
      const source = new FakeEventSource();
      sources.push(source);
      return source;
    },
    onPageHide(listener) {
      pageHide.add(listener);
      return () => pageHide.delete(listener);
    },
    onBecameVisible(listener) {
      visible.add(listener);
      return () => visible.delete(listener);
    },
    onBecameHidden(listener) {
      hidden.add(listener);
      return () => hidden.delete(listener);
    },
    beacons,
    get hidden() {
      return tab.hidden;
    },
    set hidden(value: boolean) {
      tab.hidden = value;
    },
    isHidden: () => tab.hidden,
    sendBeacon(url, body) {
      beacons.push({ url, body });
      return true;
    },
    streamOpens: () => sources.length,
    openStreams: () => sources.filter((source) => !source.closed).length,
    listenerCount: () => pageHide.size + visible.size + hidden.size,
    firePageHide() {
      for (const listener of [...pageHide]) listener();
    },
    fireVisible() {
      tab.hidden = false;
      for (const listener of [...visible]) listener();
    },
    fireHidden() {
      tab.hidden = true;
      for (const listener of [...hidden]) listener();
    },
  };
  return environment;
}

/* One browser profile's storage, shared by several tabs. `forTab` hands each
   tab a view that is notified of the others' revision writes, never its own,
   as a real `storage` event is. */
export interface FakeStorageHub {
  lease: Lease | null;
  revision: string | null;
  available: boolean;
  usage: Consent;
  observer: Consent;
  writes: { lease: number; revision: number };
  subscriberCount(): number;
  forTab(): TransportStorage;
}

export function createFakeStorageHub(): FakeStorageHub {
  const subscribers = new Set<{
    readonly owner: object;
    readonly listener: (revision: string) => void;
  }>();
  const hub: FakeStorageHub = {
    lease: null,
    revision: null,
    available: true,
    usage: null,
    observer: null,
    writes: { lease: 0, revision: 0 },
    subscriberCount: () => subscribers.size,
    forTab() {
      const owner = {};
      let usageMemo: Consent = null;
      let observerMemo: Consent = null;
      return {
        readLease: () => (hub.available ? hub.lease : null),
        writeLease(lease) {
          if (!hub.available) return false;
          hub.lease = lease;
          hub.writes.lease += 1;
          return true;
        },
        removeLease() {
          if (hub.available) hub.lease = null;
        },
        writeRevision(revision) {
          if (!hub.available) return;
          hub.revision = revision;
          hub.writes.revision += 1;
          for (const subscriber of [...subscribers]) {
            if (subscriber.owner !== owner) subscriber.listener(revision);
          }
        },
        subscribeRevision(listener) {
          const subscriber = { owner, listener };
          subscribers.add(subscriber);
          return () => subscribers.delete(subscriber);
        },
        usageConsent: () => (hub.available && hub.usage ? hub.usage : usageMemo),
        setUsageConsent(answer: ConsentAnswer) {
          usageMemo = answer;
          if (hub.available) hub.usage = answer;
        },
        observerConsent: () => (hub.available && hub.observer ? hub.observer : observerMemo),
        setObserverConsent(answer: ConsentAnswer) {
          observerMemo = answer;
          if (hub.available) hub.observer = answer;
        },
      };
    },
  };
  return hub;
}
