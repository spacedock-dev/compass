import { useSyncExternalStore } from 'react';
import type { Controls } from '../controls/kit';
import { EMPTY_FILTERS, type FilterState } from './filters';

/* The reader's Sessions search and filters, held for the life of the tab and never written to storage or the
   fragment (docs/design-sessions-search.md#persistence). A filter silently restored on reload would
   hide sessions, some of them waiting on the reader, so a reload is where it ends. Held outside the render so
   a poll, a view change and a trip into a session and back all leave it as it was. Each write replaces the
   snapshot, so `useSyncExternalStore` sees a change exactly when something changed. */
function create() {
  let state: FilterState = EMPTY_FILTERS;
  const listeners = new Set<() => void>();
  const set = (next: FilterState): void => {
    if (next === state) return;
    state = next;
    for (const listener of [...listeners]) listener();
  };
  return {
    get: (): FilterState => state,
    set,
    reset: (): void => set(EMPTY_FILTERS),
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export type FilterStore = ReturnType<typeof create>;

const held = new WeakMap<object, FilterStore>();

/* One per controls instance, which is one per shell: the sample session's second shell keeps its own. */
export function filterStoreFor(controls: Controls): FilterStore {
  let found = held.get(controls);
  if (!found) {
    found = create();
    held.set(controls, found);
  }
  return found;
}

export function useFilterState(controls: Controls): readonly [FilterState, FilterStore] {
  const store = filterStoreFor(controls);
  const state = useSyncExternalStore(store.subscribe, store.get);
  return [state, store] as const;
}
