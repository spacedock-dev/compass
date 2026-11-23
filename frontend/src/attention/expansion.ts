import { useSyncExternalStore } from 'react';
import type { Controls } from '../controls/kit';
import type { Section } from './model';

/* Which Attention sections the reader has expanded past their first three subjects, held by section name
   for the life of the tab and never written to storage (docs/design-reader-state.md, "An expanded
   Attention section"). It is the reader's, so a revision that reorders or replaces the subjects does not
   touch it: the section is the identity, and a flag set while a section held nine rows is still set when
   it holds four. The list is closed, so nothing a payload says can grow it. */
export const EXPANDABLE: readonly Section[] = ['needs', 'close'];

function create() {
  const open = new Set<string>();
  const listeners = new Set<() => void>();
  return {
    has: (section: string): boolean => open.has(section),
    toggle(section: string): void {
      if (!(EXPANDABLE as readonly string[]).includes(section)) return;
      if (!open.delete(section)) open.add(section);
      for (const listener of [...listeners]) listener();
    },
    /* A string, so a subscriber's snapshot changes exactly when a flag does. */
    snapshot: (): string => [...open].sort().join(','),
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export type Expansion = ReturnType<typeof create>;

const held = new WeakMap<object, Expansion>();

/* One per controls instance, which is one per document. */
export function expansionFor(controls: Controls): Expansion {
  let found = held.get(controls);
  if (!found) {
    found = create();
    held.set(controls, found);
  }
  return found;
}

export function useExpansion(controls: Controls): Expansion {
  const expansion = expansionFor(controls);
  useSyncExternalStore(expansion.subscribe, expansion.snapshot);
  return expansion;
}
