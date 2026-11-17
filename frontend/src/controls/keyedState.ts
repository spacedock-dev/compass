import type { Clock, TimerHandle } from '../transport/ports';

/* A confirmation cue (Copied, Raise sent) is the reader's own answer to a
   press, so it has to outlive the node it was drawn on: the board redraws on
   every revision and a cue held by a node would vanish with it. Held by key
   instead, and stamped, because never expiring is the worse lie of the two: a
   row would read SENT for the rest of the run. 30 s is longer than the 20 s
   idle render, so a cue's life is not decided by when a render lands, and
   short enough that nobody reads it as a property of the session. The cap is
   the legacy one: a board carries hundreds of rows and a tab stays open for
   hours. */
export const CUE_TTL_MS = 30_000;
export const CUE_LIMIT = 32;

/** The legacy key shape: the lane, then the exact harness and sid, NUL-joined so no value can forge another's key. */
export function laneKey(
  lane: string,
  harness: string | undefined,
  sid: string | undefined,
): string {
  return `${lane}\u0000${harness ?? ''}\u0000${sid ?? ''}`;
}

export interface KeyedStateOptions {
  readonly clock: Clock;
  /** null holds an entry until something forgets it, as the More menu's briefing result does. */
  readonly ttlMs: number | null;
  /** null is unbounded; otherwise the newest `limit` entries are kept. */
  readonly limit: number | null;
}

interface Held<S> {
  readonly state: S;
  readonly at: number;
}

/* Map insertion order is recency order (delete before set), so the first key is
   both the right one to evict and the next to expire. `read` is pure: it
   compares the stamp with the clock and deletes nothing, because it runs
   inside `useSyncExternalStore`'s snapshot. The one timer exists only so a
   subscriber is told when the entry lapses, since no render is otherwise due.
   It is armed by `activate` and dropped by `deactivate`, which is what lets
   StrictMode's effect, cleanup, effect leave exactly one. */
export function createKeyedState<S>(options: KeyedStateOptions) {
  const { clock, ttlMs, limit } = options;
  const entries = new Map<string, Held<S>>();
  const listeners = new Set<() => void>();
  let timer: TimerHandle | null = null;
  let active = false;

  const live = (held: Held<S>): boolean => ttlMs === null || clock.now() - held.at < ttlMs;

  function notify(): void {
    for (const listener of [...listeners]) listener();
  }

  function disarm(): void {
    if (timer !== null) clock.clearTimeout(timer);
    timer = null;
  }

  function purge(): boolean {
    let removed = false;
    for (const [key, held] of entries) {
      if (live(held)) continue;
      entries.delete(key);
      removed = true;
    }
    return removed;
  }

  function arm(): void {
    disarm();
    if (!active || ttlMs === null) return;
    const [first] = entries.values();
    if (!first) return;
    timer = clock.setTimeout(
      () => {
        timer = null;
        const removed = purge();
        arm();
        if (removed) notify();
      },
      Math.max(0, first.at + ttlMs - clock.now()),
    );
  }

  return {
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    read(key: string): S | undefined {
      const held = entries.get(key);
      return held && live(held) ? held.state : undefined;
    },
    remember(key: string, state: S): void {
      entries.delete(key);
      entries.set(key, { state, at: clock.now() });
      purge();
      if (limit !== null) {
        while (entries.size > limit) {
          const [oldest] = entries.keys();
          if (oldest === undefined) break;
          entries.delete(oldest);
        }
      }
      arm();
      notify();
    },
    forget(key: string): void {
      if (!entries.delete(key)) return;
      arm();
      notify();
    },
    clear(): void {
      if (entries.size === 0) return;
      entries.clear();
      disarm();
      notify();
    },
    size: (): number => entries.size,
    activate(): void {
      active = true;
      arm();
    },
    deactivate(): void {
      active = false;
      disarm();
    },
  };
}

export type KeyedState<S> = ReturnType<typeof createKeyedState<S>>;
