import { useSyncExternalStore } from 'react';
import { STORAGE_KEYS, type ConsentAnswer, type ConsentStore } from '../storage';
import { useDisplayed, useShell } from '../shell/context';
import type { BrowserRuntime } from '../transport/browser';

/* Quota consent remains browser-owned. Reader-started goal summaries use the server's durable off switch, and
   the old browser answer is read only for a decline, which the upgrade keeps rather than opting the reader back
   in. Turning summaries back on here writes `granted`, which no longer gates anything.
   [The widening](../../../docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts) */

export type Consent = ConsentAnswer | null;

interface ConsentLane {
  read(): Consent;
  /** Records the answer, and tells every reader of it. Returns whether storage took the write. */
  answer(value: ConsentAnswer): boolean;
  subscribe(listener: () => void): () => void;
}

function consentLane(store: ConsentStore, key: string): ConsentLane {
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const listener of [...listeners]) listener();
  };
  /* Another tab's answer arrives as a storage event. The document is read here rather than imported, so a
     test without a window still builds the lane. */
  const onStorage = (event: { readonly key: string | null }) => {
    if (event.key === null || event.key === key) notify();
  };
  return {
    read: () => store.get(),
    answer(value) {
      const stored = store.set(value);
      notify();
      return stored;
    },
    subscribe(listener) {
      if (listeners.size === 0 && typeof window !== 'undefined')
        window.addEventListener('storage', onStorage);
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && typeof window !== 'undefined')
          window.removeEventListener('storage', onStorage);
      };
    },
  };
}

/* The selected quota window, by vendor and window key, held for the life of the tab. `''` is none. */
function selectionLane() {
  let key = '';
  const listeners = new Set<() => void>();
  return {
    read: (): string => key,
    set(next: string): void {
      if (next === key) return;
      key = next;
      for (const listener of [...listeners]) listener();
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export type SelectionLane = ReturnType<typeof selectionLane>;

export interface Held {
  readonly usage: ConsentLane;
  readonly observer: ConsentLane;
  readonly selection: SelectionLane;
}

const held = new WeakMap<BrowserRuntime, Held>();

export function heldFor(runtime: BrowserRuntime): Held {
  let lane = held.get(runtime);
  if (!lane) {
    lane = {
      usage: consentLane(runtime.storage.usageConsent, STORAGE_KEYS.usageConsent),
      observer: consentLane(runtime.storage.observerConsent, STORAGE_KEYS.observerConsent),
      selection: selectionLane(),
    };
    held.set(runtime, lane);
  }
  return lane;
}

/** The consent this origin has recorded: `null` is unanswered. The quota fetch reads unanswered as on; nothing
    else reads it as granted. */
export function useConsent(kind: 'usage' | 'observer'): Consent {
  const lane = heldFor(useShell().runtime)[kind];
  return useSyncExternalStore(lane.subscribe, lane.read);
}

export function useSelectedWindow(): string {
  const lane = heldFor(useShell().runtime).selection;
  return useSyncExternalStore(lane.subscribe, lane.read);
}

/* The server raises the flag exactly when a discovered harness would fetch with a credential. A disk-read
   or pushed-receipt producer must not raise it, because the disclosure would then be describing a request
   that never happens. `=== true`: any other value, including a truthy string, offers nothing. */
export function useUsageOffered(): boolean {
  return useDisplayed((snapshot) => snapshot.data?.usage_fetch === true);
}
