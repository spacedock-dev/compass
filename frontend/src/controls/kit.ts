import { createContext, useContext, useSyncExternalStore } from 'react';
import type { FocusOutcome, SessionIdentity } from '../api/types';
import type { MemoState, MemoStore } from '../storage';
import type { Clock } from '../transport/ports';
import { createDisclosureStore } from './disclosureStore';
import { createFieldMemory } from './fieldMemory';
import { createFocusLane } from './focusLane';
import { CUE_LIMIT, CUE_TTL_MS, createKeyedState, type KeyedState } from './keyedState';

/** One sentence for the polite region the shell owns. The key names the event, so a repeat press is a new key. */
export type Announce = (key: string, text: string) => void;

export interface ClipboardLike {
  writeText(text: string): Promise<void>;
}

export type CueState =
  | 'copied'
  | 'failed'
  | 'sending'
  | 'sent'
  | 'declined'
  | 'throttled'
  | 'stale';
export type BriefingState = 'copied' | 'error';

export interface ControlsDeps {
  readonly clock: Clock;
  readonly announce: Announce;
  readonly memo: MemoStore;
  /** Resolved on every press, never at construction: a context with no clipboard reads as unavailable. */
  readonly clipboard?: () => ClipboardLike | null;
  /** The runtime's `focus`. Absent means the feature is off for this run, and no raise control draws. */
  readonly focus?: (identity: SessionIdentity) => Promise<FocusOutcome>;
  readonly reducedMotion?: () => boolean;
  /** A reader's own disclosure toggle began, for the commit gate's motion hold. */
  readonly noteToggle?: () => void;
}

function browserClipboard(): ClipboardLike | null {
  try {
    const clipboard = globalThis.navigator.clipboard as ClipboardLike | undefined;
    return typeof clipboard?.writeText === 'function' ? clipboard : null;
  } catch {
    return null;
  }
}

function browserReducedMotion(): boolean {
  return (
    typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

function createValueStore<T>(initial: T) {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: (): T => value,
    set(next: T): void {
      if (Object.is(next, value)) return;
      value = next;
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

export type ValueStore<T> = ReturnType<typeof createValueStore<T>>;

/* What every control needs, assembled from props so nothing here reaches for a
   global the shell does not know about. The shell owns the live regions, the
   storage instance and the runtime; this owns the reader-state lanes a redraw
   must not clear: cue by key, open disclosures, field memory, the human-context
   editor's open field and the page-wide raise busy flag. Held outside the
   rendered tree for the reason every lane in docs/design-reader-state.md is. */
export function createControls(deps: ControlsDeps) {
  let presses = 0;
  /* One field edits at a time; switching fields parks dirty drafts and originals until Done or Escape.
     Keystrokes update this memory without notifying the strip and every other memo reader. */
  const memoDrafts = new Map<string, { readonly original: string; draft: string }>();
  const memoEditing = createValueStore<{
    readonly key: string;
    readonly fresh: boolean;
  } | null>(null);
  const cues: KeyedState<CueState> = createKeyedState<CueState>({
    clock: deps.clock,
    ttlMs: CUE_TTL_MS,
    limit: CUE_LIMIT,
  });
  /* No expiry and no cap: the briefing result reads until the project or session
     scope changes, which `contextKey` makes a different key rather than a reset. */
  const briefing: KeyedState<BriefingState> = createKeyedState<BriefingState>({
    clock: deps.clock,
    ttlMs: null,
    limit: null,
  });
  return {
    clock: deps.clock,
    announce: deps.announce,
    memo: deps.memo,
    cues,
    briefing,
    disclosures: createDisclosureStore(),
    fields: createFieldMemory(),
    focusLane: createFocusLane(),
    memoEditing,
    /** Opens one human-context field for editing, remembering the words it held so Escape can put them back. */
    startMemoEdit(key: string): void {
      const previous = memoEditing.get();
      if (previous) {
        const parked = memoDrafts.get(previous.key);
        if (parked && parked.draft === parked.original) memoDrafts.delete(previous.key);
      }
      if (!memoDrafts.has(key)) {
        const original = deps.memo.read(key, true);
        memoDrafts.set(key, { original, draft: original });
      }
      memoEditing.set({ key, fresh: true });
    },
    memoDraft: (key: string): string | undefined => memoDrafts.get(key)?.draft,
    // An over-limit paste cannot autosave, but its words must still survive the editor unmounting.
    setMemoDraft(key: string, draft: string): void {
      const editing = memoDrafts.get(key);
      if (editing) editing.draft = draft;
    },
    /** Closes the editor. Escape undoes this tab's edits unless another tab saved; Done keeps what was typed. */
    finishMemoEdit(options: { readonly restore: boolean }): MemoState | undefined {
      const editing = memoEditing.get();
      if (!editing) return undefined;
      const draft = memoDrafts.get(editing.key);
      const state =
        options.restore && draft ? deps.memo.restore(editing.key, draft.original) : undefined;
      memoDrafts.delete(editing.key);
      memoEditing.set(null);
      return state;
    },
    /** The editor took focus on opening and has not been asked again. */
    memoEditingSeen(): void {
      const editing = memoEditing.get();
      if (editing?.fresh) memoEditing.set({ ...editing, fresh: false });
    },
    /** Page-wide: the daemon's raise refusal is one flag for every row, so every RAISE reads busy together. */
    raiseBusy: createValueStore(false),
    clipboard: deps.clipboard ?? browserClipboard,
    focus: deps.focus ?? null,
    reducedMotion: deps.reducedMotion ?? browserReducedMotion,
    noteToggle: deps.noteToggle ?? (() => undefined),
    press: (): number => {
      presses += 1;
      return presses;
    },
    /** Arms the cue timers; the returned function stops them. Idempotent, so StrictMode's second effect is harmless. */
    activate(): () => void {
      cues.activate();
      briefing.activate();
      return () => {
        cues.deactivate();
        briefing.deactivate();
      };
    },
  };
}

export type Controls = ReturnType<typeof createControls>;

export const ControlsContext = createContext<Controls | null>(null);

export function useControls(): Controls {
  const controls = useContext(ControlsContext);
  if (!controls) throw new Error('A shared control was rendered outside a ControlsProvider.');
  return controls;
}

export function useKeyedValue<S extends string>(store: KeyedState<S>, key: string): S | undefined {
  return useSyncExternalStore(store.subscribe, () => store.read(key));
}

export function useValueStore<T>(store: ValueStore<T>): T {
  return useSyncExternalStore(store.subscribe, store.get);
}
