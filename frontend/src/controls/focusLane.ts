export interface FocusKeyOptions {
  /** The key focus goes to when this control is removed while focused, as the analysis box's Cancel names its Analyze. */
  readonly fallback?: string;
}

interface Entry {
  readonly element: HTMLElement;
  readonly fallback: string | undefined;
}

function offscreen(element: HTMLElement): boolean {
  const view = element.ownerDocument.defaultView;
  if (!view) return false;
  const rect = element.getBoundingClientRect();
  return (
    rect.bottom <= 0 ||
    rect.top >= view.innerHeight ||
    rect.right <= 0 ||
    rect.left >= view.innerWidth
  );
}

/* A persistent React node keeps its own focus, so most of the legacy focus lane
   has nothing left to do. What remains is the case the node cannot cover:
   the focused control is removed (or replaced under the same key), and focus has
   to land somewhere the reader would expect rather than on the document body.

   Keys sit in a Map and are compared by identity, never interpolated into a
   selector: a key is built from project and session text a hostile payload could
   write, which is what the legacy hostile-key test exists to prove. The old
   target's visibility is read when it is removed, not when focus is restored,
   because by then it is gone. A control wholly outside the viewport is
   restored with `preventScroll`, so an unrelated revision does not drag a reader
   who scrolled away back down to the control they had parked on; one that
   intersected the viewport keeps the browser's ordinary scroll-into-view, so
   the control they were using stays reachable
   ([Document scroll](docs/design-reader-state.md#document-scroll)). */
export function createFocusLane() {
  const entries = new Map<string, Entry>();

  function focus(key: string, options: { readonly preventScroll?: boolean } = {}): boolean {
    const entry = entries.get(key);
    if (!entry) return false;
    entry.element.focus({ preventScroll: options.preventScroll === true });
    return true;
  }

  return {
    register(key: string, element: HTMLElement, options: FocusKeyOptions = {}): () => void {
      const entry: Entry = { element, fallback: options.fallback };
      entries.set(key, entry);
      return () => {
        if (entries.get(key) === entry) entries.delete(key);
        const document = element.ownerDocument;
        if (document.activeElement !== element) return;
        const preventScroll = offscreen(element);
        // After the commit that removes the node has finished, so a same-key replacement is registered by now.
        queueMicrotask(() => {
          const active = document.activeElement;
          if (active && active !== document.body && active !== element) return;
          if (focus(key, { preventScroll })) return;
          if (entry.fallback !== undefined) focus(entry.fallback, { preventScroll });
        });
      };
    },
    focus,
    /** The control registered under a key, or undefined where none is drawn. */
    element: (key: string): HTMLElement | undefined => entries.get(key)?.element,
    size: (): number => entries.size,
  };
}

export type FocusLane = ReturnType<typeof createFocusLane>;
