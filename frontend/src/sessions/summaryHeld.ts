import { useSyncExternalStore } from 'react';
import type { LargestRead, SummaryGrant, SummaryJob } from '../api/summary';
import type { BrowserRuntime } from '../transport/browser';

/* What this tab keeps about a session's summary between board refreshes, in memory only and never in browser
   storage: the last press's answer, the notice that answer carried, and whether the page has already posted the
   one summary a finished session gets on open. The summary itself, its job and the grant are the server's,
   read from the board and the focused context on every revision; nothing here outlives a reload, so "once
   per page load" is exactly this store's lifetime
   ([the inventory](../../../docs/design-reader-state.md#the-inventory)). */

export interface SessionSummaryHeld {
  /** The job a 202 named, drawn until the focused context publishes it. */
  readonly job: SummaryJob | null;
  /** The board revision that 202 answered against: a focused context read after it is the server's word. */
  readonly jobAt: number;
  /** The notice the last start's reply carried, until the next start's reply replaces it or a turn-off. */
  readonly notice: Readonly<Record<string, unknown>> | null;
  /** The last refusal the server answered a press or an open with, until the next press. */
  readonly refusal: { readonly reason: string; readonly largest: LargestRead | null } | null;
  /** A press whose answer was lost, said in place until the next press. */
  readonly failed: string;
  /** The page has posted, or has decided not to post, this session's open summary for this page load. */
  readonly opened: boolean;
  /** That open's request is in flight. */
  readonly opening: boolean;
  /** When the first press on Delete summary armed it, in the clock's milliseconds, or 0 while it is not armed. */
  readonly deleteArmedAt: number;
  /** When this tab last deleted the summary, in the clock's milliseconds, or 0: said until the next start. */
  readonly deletedAt: number;
}

const EMPTY: SessionSummaryHeld = {
  job: null,
  jobAt: 0,
  notice: null,
  refusal: null,
  failed: '',
  opened: false,
  opening: false,
  deleteArmedAt: 0,
  deletedAt: 0,
};

export interface SummaryHeldStore {
  get(key: string): SessionSummaryHeld;
  patch(key: string, change: Partial<SessionSummaryHeld>): void;
  /** Drops every held notice: a turn-off ends what the notice described. */
  clearNotices(): void;
  /** The grant a consent reply answered, over the board until a board drawn after it arrives. */
  grant(): { readonly block: SummaryGrant; readonly generated: number } | null;
  setGrant(block: SummaryGrant | null, generated: number): void;
  subscribe(listener: () => void): () => void;
  version(): number;
}

function createStore(): SummaryHeldStore {
  const rows = new Map<string, SessionSummaryHeld>();
  let granted: { readonly block: SummaryGrant; readonly generated: number } | null = null;
  let version = 0;
  const listeners = new Set<() => void>();
  const notify = () => {
    version += 1;
    for (const listener of [...listeners]) listener();
  };
  return {
    get: (key) => rows.get(key) ?? EMPTY,
    patch(key, change) {
      rows.set(key, { ...(rows.get(key) ?? EMPTY), ...change });
      notify();
    },
    clearNotices() {
      for (const [key, row] of rows) if (row.notice) rows.set(key, { ...row, notice: null });
      notify();
    },
    grant: () => granted,
    setGrant(block, generated) {
      granted = block ? { block, generated } : null;
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    version: () => version,
  };
}

const stores = new WeakMap<BrowserRuntime, SummaryHeldStore>();

export function summaryHeldFor(runtime: BrowserRuntime): SummaryHeldStore {
  let store = stores.get(runtime);
  if (!store) {
    store = createStore();
    stores.set(runtime, store);
  }
  return store;
}

export function useSummaryHeld(store: SummaryHeldStore, key: string): SessionSummaryHeld {
  useSyncExternalStore(store.subscribe, store.version, store.version);
  return store.get(key);
}

/* The grant as drawn: a consent reply's answer stands only over the board it was answered against, so a later
   board, which already carries the change, takes over again. */
export function grantShown(
  store: SummaryHeldStore,
  board: SummaryGrant | null,
  generated: number,
): SummaryGrant | null {
  const held = store.grant();
  return held && held.generated >= generated ? held.block : board;
}
