import { readBootstrap } from '../api/bootstrap';
import { createApiClient, type FetchLike } from '../api/client';
import { exactIdentity } from '../api/identity';
import type { FocusOutcome, SessionIdentity } from '../api/types';
import { createBoardStore, type BoardSnapshot } from '../store/board';
import { createContextLoader, type ContextScope } from './context';
import { createRecordLoader, type RecordScope } from './record';
import { createLiveTransport } from './live';
import { createPendingRegistry, type PendingToken } from './pending';
import type { Environment, TimerHandle, TransportStorage } from './ports';
import { createRefreshController, type DataOutcome, type RefreshSink } from './refresh';
import { createRevisionMemo } from './revision';

export interface RuntimeOptions {
  readonly fetch: FetchLike;
  readonly storage: TransportStorage;
  readonly env: Environment;
  /** `location.search` of the page. */
  readonly search: string;
  readonly doc: Pick<Document, 'querySelector'> | null;
  /** Where a consumer holds back painting (see `store/commit-gate`). Absent means paint at once. */
  readonly paint?: RefreshSink['paint'];
  readonly announce?: (key: string, sentence: string) => void;
  /** The entry ended; the announcer drops its guard for this key (see `PendingDeps.forget`). */
  readonly forget?: (key: string) => void;
}

/* The one place the board's resources are started and stopped. The store and
   the pending-token registry belong to the runtime and live as long as it
   does, so a view that unmounts and remounts still has the last accepted board
   and an in-flight action's re-press guard; the registry's timers only abort
   or clear their own entries and reach no network on their own. Every fetch,
   socket, timer and listener of the live board belongs to an `Owned` set that
   `start` creates and `stop` tears down whole.

   `stop` is the revivable teardown (the last holder leaving). `dispose` is
   terminal: a disposed or superseded runtime cannot be revived by a stale
   holder's `acquire`. Release functions are tied to the generation that
   issued them, so one outliving a stop cannot drive the count negative or tear
   down a later holder.

   Nothing in here issues a POST. Actions are the caller's explicit
   `client.post*` calls, so a reconnect, a poll, a store subscription or a
   remount cannot replay one. */
export function createBoardRuntime(options: RuntimeOptions) {
  const { env, storage } = options;
  const bootstrap = readBootstrap(options.search, options.doc);
  const client = createApiClient({ fetch: options.fetch });
  const store = createBoardStore({ now: env.clock.now });
  const revisions = createRevisionMemo();

  interface Owned {
    readonly refresh: ReturnType<typeof createRefreshController>;
    readonly context: ReturnType<typeof createContextLoader>;
    readonly record: ReturnType<typeof createRecordLoader>;
    readonly live: ReturnType<typeof createLiveTransport>;
  }

  const pendingRegistry = createPendingRegistry({
    clock: env.clock,
    onChange: () => store.setPending(pendingRegistry.keys()),
    announce: options.announce ?? (() => undefined),
    ...(options.forget ? { forget: options.forget } : {}),
  });

  let owned: Owned | null = null;
  let holders = 0;
  let generation = 0;
  let teardown: TimerHandle | null = null;
  let disposed = false;
  let focusInFlight = false;

  function create(): Owned {
    const sink: RefreshSink = {
      async fetchData(signal): Promise<DataOutcome> {
        const result = await client.getData({
          showAll: bootstrap.showAll,
          usage: storage.usageConsent() === 'granted',
          signal,
        });
        switch (result.kind) {
          case 'ok':
            return { kind: 'data', body: result.body, revision: result.revision };
          case 'http-error':
            return { kind: 'failed', failure: { kind: 'http-error', status: result.status } };
          case 'malformed':
            return { kind: 'failed', failure: { kind: 'malformed', status: result.status } };
          case 'network-error':
            return { kind: 'failed', failure: { kind: 'network-error' } };
          case 'aborted':
            return { kind: 'aborted' };
        }
      },
      manualInFlight: (active) => store.setManualRefreshing(active),
      accepted: (body, revision) => store.acceptData(body, revision),
      failed: (failure) => store.recordFailure(failure),
      paint: options.paint ?? (() => Promise.resolve()),
    };
    const refresh = createRefreshController({ sink, revisions });
    return {
      refresh,
      context: createContextLoader({ client, store }),
      record: createRecordLoader({ client, store }),
      live: createLiveTransport({
        env,
        storage,
        revisions,
        onWake: (revision) => refresh.wake(revision),
        onPoll: () => void refresh.poll(),
      }),
    };
  }

  function start(): void {
    if (disposed || owned) return;
    owned = create();
    owned.live.start();
  }

  function stop(): void {
    if (teardown !== null) env.clock.clearTimeout(teardown);
    teardown = null;
    holders = 0;
    generation += 1;
    const closing = owned;
    owned = null;
    if (!closing) return;
    closing.live.dispose();
    closing.refresh.dispose();
    closing.context.dispose();
    closing.record.dispose();
  }

  function dispose(): void {
    stop();
    disposed = true;
    pendingRegistry.dispose();
    store.setPending([]);
  }

  const pending = {
    start(key: string, busy: string, say = ''): PendingToken | null {
      const token = pendingRegistry.start(key, busy, say);
      if (token) store.setPending(pendingRegistry.keys());
      return token;
    },
    end(key: string, token: PendingToken | null | undefined): boolean {
      const ended = pendingRegistry.end(key, token);
      if (ended) store.setPending(pendingRegistry.keys());
      return ended;
    },
    has: (key: string): boolean => pendingRegistry.has(key),
  };

  return {
    store,
    client,
    bootstrap,
    pending,
    start,
    stop,
    dispose,

    /* For a component effect. React's StrictMode runs effect, cleanup, effect
       on mount; teardown is deferred one tick so that sequence reuses the
       running owner instead of opening a second stream and reading twice. */
    acquire(): () => void {
      if (disposed) return () => undefined;
      holders += 1;
      if (teardown !== null) env.clock.clearTimeout(teardown);
      teardown = null;
      start();
      const issued = generation;
      let released = false;
      return () => {
        if (released || issued !== generation) return;
        released = true;
        holders -= 1;
        if (holders > 0 || teardown !== null) return;
        teardown = env.clock.setTimeout(() => {
          teardown = null;
          if (holders === 0) stop();
        }, 0);
      };
    },

    refresh: (flags: { readonly manual?: boolean } = {}): Promise<void> =>
      owned?.refresh.refresh(flags) ?? Promise.resolve(),
    /* Whether this tab holds the live stream: the one tab that raises a stage banner, so two open tabs do not
       both. False before the runtime is owned. */
    isLeader: (): boolean => owned?.live.isLeader() ?? false,
    loadContext: (scope: ContextScope): void => owned?.context.load(scope),
    openRecord: (scope: RecordScope): (() => void) =>
      owned?.record.open(scope) ?? (() => undefined),
    readMoreRecord: (scope: RecordScope): Promise<void> =>
      owned?.record.more(scope) ?? Promise.resolve(),
    /* The newest page again, once per change of the session's published activity, so what it writes while the
       page is open is held here and never depends on the board's tail-bound context. */
    refreshRecord: (scope: RecordScope, stamp: number): Promise<void> =>
      owned?.record.refresh(scope, stamp) ?? Promise.resolve(),
    /* The one read the page makes for the reader: the older pages a reading their own press finished cites.
       It ends on the test, the record's start, a page that moved nothing, or RESOLVE_MAX_PAGES. */
    resolveRecord: (
      scope: RecordScope,
      until: (snapshot: BoardSnapshot) => boolean,
    ): Promise<void> => owned?.record.resolve(scope, until) ?? Promise.resolve(),
    requestObserverSummary: (scope: ContextScope): Promise<void> =>
      owned?.context.requestObserverSummary(scope) ?? Promise.resolve(),

    /* One explicit attempt at a time, as the legacy raise control was: a press
       while one is in flight is answered locally as throttled and sends
       nothing, and so does an identity or capability that is empty. */
    async focus(identity: SessionIdentity): Promise<FocusOutcome> {
      const exact = exactIdentity(identity);
      if (!exact || !bootstrap.focusCapability) return 'unavailable';
      if (focusInFlight) return 'throttled';
      focusInFlight = true;
      try {
        return await client.focus({ identity: exact, capability: bootstrap.focusCapability });
      } finally {
        focusInFlight = false;
      }
    },
  };
}

export type BoardRuntime = ReturnType<typeof createBoardRuntime>;

const SLOT = Symbol.for('compass.board.runtime');

/* Module replacement re-runs the module that creates the runtime. The previous
   one is disposed here, before the replacement can start, so a hot update
   cannot leave two owners with a stream each, and it stays disposed: a stale
   holder cannot revive it. Installing the runtime that is already installed
   changes nothing. */
export function replaceRuntime(
  next: BoardRuntime,
  holder: Record<symbol, BoardRuntime | undefined> = globalThis as unknown as Record<
    symbol,
    BoardRuntime | undefined
  >,
): BoardRuntime {
  if (holder[SLOT] === next) return next;
  holder[SLOT]?.dispose();
  holder[SLOT] = next;
  return next;
}
