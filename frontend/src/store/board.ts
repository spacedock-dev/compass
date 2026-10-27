import type {
  ModelNoticeRecord,
  PayloadData,
  ProjectContext,
  SemanticFact,
  SessionRecord,
} from '../api/types';

export type DataFailure =
  | { readonly kind: 'http-error'; readonly status: number }
  | { readonly kind: 'network-error' }
  | { readonly kind: 'malformed'; readonly status: number };

/* `data` and `error` are independent on purpose. A failed read over a loaded
   context keeps the previous data beside the new error, which a reader keying
   off `data` alone cannot tell from a clean resolve, so the five states are
   derived from both fields (`selectContextState`). */
export interface ContextEntry {
  readonly data: ProjectContext | null;
  readonly revision: number;
  readonly error: DataFailure | null;
}

export interface RecordEntry {
  readonly entries: readonly SemanticFact[];
  readonly next: string | null;
  readonly reachedStart: boolean;
  readonly bound: SessionRecord['bound'];
  readonly scannedBytes: number;
  readonly status: 'idle' | 'loading' | 'loaded' | 'error' | 'stale' | 'unsupported';
  readonly error: DataFailure | { readonly kind: 'unavailable' | 'stale' } | null;
  readonly pages: number;
  readonly restarted: boolean;
}

export const EMPTY_RECORD: RecordEntry = {
  entries: [],
  next: null,
  reachedStart: false,
  bound: null,
  scannedBytes: 0,
  status: 'idle',
  error: null,
  pages: 0,
  restarted: false,
};

export interface BoardSnapshot {
  /** The last accepted body, exactly as the server sent it. */
  readonly data: PayloadData | null;
  /** The `X-Compass-Revision` of that body, or '' when it carried none. */
  readonly revision: string;
  readonly acceptedCount: number;
  /** Failed current reads since the last accepted body. */
  readonly failures: number;
  readonly lastFailure: DataFailure | null;
  readonly lastSuccessAt: number | null;
  readonly manualRefreshing: boolean;
  readonly firstBuild: string;
  readonly contexts: ReadonlyMap<string, ContextEntry>;
  readonly records: ReadonlyMap<string, RecordEntry>;
  readonly observer: {
    readonly requests: readonly string[];
    readonly states: ReadonlyMap<string, 'ready' | 'error'>;
    /** The goal notice the last explicit Summarize reply carried, per context key. Held outside the context
        entry because the server sends it only on that reply, and the next passive read replaces the entry. */
    readonly notices: ReadonlyMap<string, ModelNoticeRecord>;
  };
  readonly pending: readonly string[];
}

const MAX_REPORTED_LISTENER_ERRORS = 10;
const LISTENER_ERROR_WINDOW_MS = 60_000;

const INITIAL: BoardSnapshot = Object.freeze({
  data: null,
  revision: '',
  acceptedCount: 0,
  failures: 0,
  lastFailure: null,
  lastSuccessAt: null,
  manualRefreshing: false,
  firstBuild: '',
  contexts: new Map(),
  records: new Map(),
  observer: { requests: [], states: new Map(), notices: new Map() },
  pending: [],
});

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/* An immutable snapshot replaced on every change and left alone otherwise, so
   `useSyncExternalStore` sees a stable identity while nothing happened. The
   store only holds what was accepted; when to SHOW it is `commit-gate`'s
   decision, so acceptance and paint stay separate. */
export function createBoardStore(deps: {
  readonly now: () => number;
  /** Where a throwing subscriber's error goes. The default hands it to the page's own error reporting. */
  readonly reportError?: (error: unknown) => void;
}) {
  let snapshot: BoardSnapshot = INITIAL;
  let listenerErrors = 0;
  let windowStart = Number.NEGATIVE_INFINITY;
  let windowReports = 0;
  const listeners = new Set<() => void>();
  const report =
    deps.reportError ??
    ((error: unknown) => {
      globalThis.reportError?.(error);
    });

  /* Each listener is called on its own so one that throws cannot turn an
     accepted body into a counted failure, starve the listeners after it, or
     leave the refresh run that published it unreleased. Reports are capped per
     minute rather than for the store's life, because a listener that throws on
     every change would otherwise flood the page's error handler at the poll
     rate, while a new bug an hour later must still be seen; the count is kept
     regardless. */
  function publish(next: BoardSnapshot): void {
    snapshot = next;
    for (const listener of [...listeners]) {
      try {
        listener();
      } catch (error) {
        listenerErrors += 1;
        const at = deps.now();
        if (at - windowStart >= LISTENER_ERROR_WINDOW_MS) {
          windowStart = at;
          windowReports = 0;
        }
        if (windowReports < MAX_REPORTED_LISTENER_ERRORS) {
          windowReports += 1;
          try {
            report(error);
          } catch {
            /* a failing reporter must not break the publish either */
          }
        }
      }
    }
  }

  return {
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: (): BoardSnapshot => snapshot,
    subscriberCount: (): number => listeners.size,
    listenerErrorCount: (): number => listenerErrors,

    acceptData(body: PayloadData, revision: string): void {
      const build = typeof body.build === 'string' ? body.build : '';
      publish({
        ...snapshot,
        data: body,
        revision,
        acceptedCount: snapshot.acceptedCount + 1,
        failures: 0,
        lastFailure: null,
        lastSuccessAt: deps.now(),
        firstBuild: snapshot.firstBuild || build,
      });
    },

    recordFailure(failure: DataFailure): void {
      publish({ ...snapshot, failures: snapshot.failures + 1, lastFailure: failure });
    },

    setManualRefreshing(active: boolean): void {
      if (snapshot.manualRefreshing === active) return;
      publish({ ...snapshot, manualRefreshing: active });
    },

    setContext(key: string, entry: ContextEntry): void {
      const contexts = new Map(snapshot.contexts);
      contexts.set(key, entry);
      publish({ ...snapshot, contexts });
    },

    setRecord(key: string, entry: RecordEntry): void {
      const records = new Map(snapshot.records);
      records.set(key, entry);
      publish({ ...snapshot, records });
    },

    dropRecord(key: string): void {
      if (!snapshot.records.has(key)) return;
      const records = new Map(snapshot.records);
      records.delete(key);
      publish({ ...snapshot, records });
    },

    setObserverRequest(key: string, active: boolean): void {
      const has = snapshot.observer.requests.includes(key);
      if (has === active) return;
      const requests = active
        ? [...snapshot.observer.requests, key]
        : snapshot.observer.requests.filter((candidate) => candidate !== key);
      publish({ ...snapshot, observer: { ...snapshot.observer, requests } });
    },

    setObserverState(key: string, state: 'ready' | 'error'): void {
      const states = new Map(snapshot.observer.states);
      states.set(key, state);
      publish({ ...snapshot, observer: { ...snapshot.observer, states } });
    },

    /** Kept until the next explicit Summarize reply replaces it or a turn-off clears it (`null`). */
    setObserverNotice(key: string, notice: ModelNoticeRecord | null): void {
      const had = snapshot.observer.notices.get(key);
      if (had === notice || (!had && !notice)) return;
      const notices = new Map(snapshot.observer.notices);
      if (notice) notices.set(key, notice);
      else notices.delete(key);
      publish({ ...snapshot, observer: { ...snapshot.observer, notices } });
    },

    clearObserverNotices(): void {
      if (snapshot.observer.notices.size === 0) return;
      publish({ ...snapshot, observer: { ...snapshot.observer, notices: new Map() } });
    },

    setPending(keys: readonly string[]): void {
      if (sameList(snapshot.pending, keys)) return;
      publish({ ...snapshot, pending: [...keys] });
    },
  };
}

export type BoardStore = ReturnType<typeof createBoardStore>;
