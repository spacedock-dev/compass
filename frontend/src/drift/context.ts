import { createContext, useContext } from 'react';
import type { DriftModel } from './model';
import type { DriftCtx } from './state';
import type { Criterion } from './shape';

/* What the Drift section's parts read, assembled once per render by `DriftProvider`: the model every part
   draws from, and the shell's owners. */
/* One press of a cited entry: which finding of which reading, and the control it was pressed on, so
   focus can go back. */
export interface Jump {
  readonly session: string;
  readonly readAt: unknown;
  readonly key: string;
  readonly origin: HTMLElement | null;
  /** The one cited entry a chip named, where focus lands; null for the finding's first cited row. */
  readonly entry: string | null;
}

/* The cited entries a press could not bring into the list once its pages were read, and why the read ended:
   at the record's start, short of it (the page cap or a failed page), or with every entry held but set aside by
   the reading's own rules (`count` is 0 then). */
export interface JumpMissing {
  readonly press: Jump;
  readonly count: number;
  readonly reason: 'start' | 'stopped' | 'unshown';
}

export interface DriftValue {
  readonly ctx: DriftCtx;
  readonly model: DriftModel;
  readonly finding: Criterion | null;
  readonly jump: Jump | null;
  /** What the last press could not load, kept until the next press, a new reading or another session. */
  readonly jumpMissing: JumpMissing | null;
  readonly chooseFinding: (key: string, origin?: HTMLElement | null, entry?: string | null) => void;
}

export const DriftContext = createContext<DriftValue | null>(null);

export function useDrift(): DriftValue {
  const value = useContext(DriftContext);
  if (!value) throw new Error('A Drift part was rendered outside the Drift provider.');
  return value;
}
