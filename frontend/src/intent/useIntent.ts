import { createContext, useContext, useSyncExternalStore } from 'react';
import type { Row } from '../observed';
import type { Shell } from '../shell/context';
import { useShell } from '../shell/context';
import type { Ctx } from './context';
import type { DraftInput } from './derive';
import { createHeld, type Held } from './held';
import type { WorkSource } from './work';

/* One Intent state per shell, made on first use and kept for the document's life, so a view that unmounts
   and returns finds the draft, the caret memory and the cue it left, and a second shell in a test or after
   a hot update never shares a word with the first. */
const contexts = new WeakMap<Shell, Ctx>();

export function intentCtxFor(shell: Shell): Ctx {
  let ctx = contexts.get(shell);
  if (!ctx) {
    ctx = { shell, held: createHeld({ clock: shell.clock, announcer: shell.announcer }) };
    contexts.set(shell, ctx);
  }
  return ctx;
}

export function useIntentCtx(): Ctx {
  return intentCtxFor(useShell());
}

/* Re-render whenever anything held changes. A keystroke changes it too, which is cheap because every editor
   is uncontrolled: React renders around a native textarea and leaves its text, caret and undo alone. */
export function useHeldVersion(held: Held): number {
  return useSyncExternalStore(held.subscribe, held.getVersion);
}

/* What the panel's parts read, assembled once per render. */
export interface Panel {
  readonly ctx: Ctx;
  readonly input: DraftInput;
  readonly session: Row;
  readonly payload: Row;
  readonly harness: string;
  readonly sid: string;
  readonly project: string;
  readonly projectKey: string;
  readonly source: WorkSource;
  readonly cap: number;
  readonly goalCap: number;
}

export const PanelContext = createContext<Panel | null>(null);

export function usePanel(): Panel {
  const panel = useContext(PanelContext);
  if (!panel) throw new Error('An Intent part was rendered outside the Intent panel.');
  return panel;
}
