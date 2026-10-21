import { useSyncExternalStore } from 'react';
import { HELD_CUE_LIMIT } from '../intent/held';
import { intentCtxFor } from '../intent/useIntent';
import type { Ctx } from '../intent/context';
import type { Row } from '../observed';
import type { Shell } from '../shell/context';
import { trackJobs } from './jobs';
import type { TimerHandle } from '../transport/ports';
import type { HeldCorrection } from './correction';

/* Everything the Drift section holds for the reader that a redraw must not lose, kept in memory and never
   written to browser storage (`docs/design-reader-state.md` names each row). The board redraws on every
   revision, so state held by a node would go with it; these are held outside the rendered tree and keyed by
   the exact harness and session id. One notification channel, a version number, as the Intent step's.

   The reading-feedback lane itself (`requests`) is the Intent step's, because Keep writes it and so does
   Analyze: one answer per session, said once. */

/* Whether Analyze can be pressed, as the drawn Drift card last showed it, so a change no press caused is said
   rather than silent. */
export interface Flip {
  shown: boolean;
  candidate: false | null;
  candidateSince: number;
  candidateData: unknown;
  saidAt: number | null;
  said: string;
  owed: string;
  line: string;
  lineAt: number;
  drawn: number;
}

/* The departures a reading carried the last time this tab drew it, and what the next reading cleared. Held
   in the tab and never stored: it says only what this tab watched happen, so a reading it never saw depart
   cannot clear. */
export interface SeenReading {
  readAt: number;
  departures: number;
  /** The reading drawn before this one, and how many departures it carried. */
  before: { readonly readAt: number; readonly departures: number } | null;
}

/** The earlier reading's departures that the reading now standing no longer finds. */
export interface ClearedDeparture {
  readonly readAt: number;
  readonly count: number;
}

export type FlipTimerName = 'hold' | 'until' | 'line' | 'say';

/* A Cancel in flight, or one that could not be confirmed, per session and for the one job it named, so
   neither outlives that job's box. */
export interface CancelNote {
  job: string;
  pending: boolean;
  failed: boolean;
}

/* A running analysis this tab has seen, whether its box was drawn, and the outcome fields as they stood when
   it was first seen, so an end can tell a new reading from the one already stored. */
export interface JobSeen {
  id: string;
  drawn: boolean;
  reading: string;
}

/* What a reply told the page that the next board will confirm or replace: the job a press started, the route
   the server now names for a harness, and the policy it answered with. The legacy page wrote these into its
   current payload; the React page never mutates a board, so they are held beside it and apply only while
   the board that was current when they were written is still the one on screen. */
export interface Overlay {
  readonly stamp: number;
  readonly jobs: Readonly<Record<string, Row>>;
  readonly routes: Readonly<Record<string, Row>>;
  readonly reading: Row | null;
}

export interface Editor {
  /** An IME composition in progress in the correction box. */
  composition: {
    input: HTMLTextAreaElement;
    held: HeldCorrection;
    before: string;
    edited: boolean;
    start: number | null;
    end: number | null;
  } | null;
  /** The session whose correction box holds focus, or null. */
  focused: string | null;
  /** A pointer pressed on a control while the correction box held an edited draft, until its click lands. */
  pointer: { id: number; target: EventTarget | null; key: string } | null;
  /** A paint the reader's editing deferred. */
  pendingRender: boolean;
}

export function createDriftState(shell: Shell) {
  const { clock } = shell;
  const listeners = new Set<() => void>();
  let version = 0;
  const flips = new Map<string, Flip>();
  const cancels = new Map<string, CancelNote>();
  const jobsSeen = new Map<string, JobSeen>();
  const corrections = new Map<string, HeldCorrection>();
  const notAccurate = new Set<string>();
  const readings = new Map<string, SeenReading>();
  const timers = new Map<FlipTimerName, { at: number; handle: TimerHandle }>();
  const wants = new Map<FlipTimerName, number | null>();
  let overlay: Overlay = { stamp: -1, jobs: {}, routes: {}, reading: null };
  const editor: Editor = { composition: null, focused: null, pointer: null, pendingRender: false };
  let epoch = 0;
  let correctionIds = 0;
  let primed = false;
  let mounted = 0;

  function notify(): void {
    version += 1;
    for (const listener of [...listeners]) listener();
  }

  /* The legacy page armed one timer per name and re-armed it for the same moment as a no-op, from inside the
     render. Here a render only records what it wants and the commit that follows arms it, so a render React
     throws away arms nothing and StrictMode's second render asks for the same moment twice. */
  function applyTimers(): void {
    for (const [name, at] of wants) {
      const current = timers.get(name);
      if (at !== null && current && current.at === at) continue;
      if (current) clock.clearTimeout(current.handle);
      timers.delete(name);
      if (at === null) continue;
      const delay = at - clock.now();
      // A moment this far off is a fixture or a clock skew, never a settle.
      if (!Number.isFinite(delay) || delay > 2 * 60_000) continue;
      timers.set(name, {
        at,
        handle: clock.setTimeout(
          () => {
            timers.delete(name);
            notify();
          },
          Math.max(0, delay),
        ),
      });
    }
    wants.clear();
  }

  return {
    flips,
    cancels,
    jobsSeen,
    corrections,
    notAccurate,
    editor,
    /* An immutable snapshot, replaced on every write, so a render that reads it has a value to depend on. */
    getOverlay: (): Overlay => overlay,
    setOverlay(next: Overlay): void {
      overlay = next;
      notify();
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getVersion: (): number => version,
    notify,

    /** One more pass of the drawn Drift card; an entry not drawn on the pass before is drawn fresh. */
    nextEpoch: (): number => {
      epoch += 1;
      return epoch;
    },
    epoch: (): number => epoch,
    nextCorrectionId: (): number => {
      correctionIds += 1;
      return correctionIds;
    },

    want(name: FlipTimerName, at: number | null): void {
      wants.set(name, at);
    },
    applyTimers,
    dispose(): void {
      for (const { handle } of timers.values()) clock.clearTimeout(handle);
      timers.clear();
      wants.clear();
    },

    isPrimed: (): boolean => primed,
    prime(): void {
      primed = true;
    },
    mountedCount: (): number => mounted,
    mount(): () => void {
      mounted += 1;
      return () => {
        mounted -= 1;
      };
    },

    /* The reading now standing for a session and how many departures it carries: the departures the one
       before it carried that this one does not are returned for as long as it stands, and the next reading,
       whatever it finds, takes the note down. The count is the latest drawn for that reading, because the
       entries a departure cites may load after the first draw. Idempotent per `readAt`, so a render that
       runs twice says the same. */
    noteReading(key: string, readAt: number, departures: number): ClearedDeparture | null {
      const seen = readings.get(key);
      if (seen && seen.readAt === readAt) {
        seen.departures = departures;
      } else {
        const before =
          seen && readAt > seen.readAt
            ? { readAt: seen.readAt, departures: seen.departures }
            : null;
        readings.delete(key);
        readings.set(key, { readAt, departures, before });
        while (readings.size > HELD_CUE_LIMIT) {
          const [oldest] = readings.keys();
          if (oldest === undefined) break;
          readings.delete(oldest);
        }
      }
      const now = readings.get(key);
      return now?.before && now.before.departures > 0 && departures === 0
        ? { readAt: now.before.readAt, count: now.before.departures }
        : null;
    },

    /* The flip ledger is bounded as the cue lanes are: past sixteen drawn sessions the oldest goes. */
    rememberFlip(key: string, flip: Flip): void {
      flips.delete(key);
      flips.set(key, flip);
      while (flips.size > HELD_CUE_LIMIT) {
        const [oldest] = flips.keys();
        if (oldest === undefined) break;
        flips.delete(oldest);
      }
    },
  };
}

export type DriftState = ReturnType<typeof createDriftState>;

export interface DriftCtx {
  readonly shell: Shell;
  /** The Intent step's context: its held state and the reading-feedback lane it shares. */
  readonly intent: Ctx;
  readonly drift: DriftState;
}

/* One Drift state per shell, made on first use and kept for the document's life, so a view that unmounts
   and returns finds the correction it left open, the cancel it was waiting on and the flip ledger. */
const contexts = new WeakMap<Shell, DriftCtx>();

export function driftCtxFor(shell: Shell): DriftCtx {
  let ctx = contexts.get(shell);
  if (!ctx) {
    const made: DriftCtx = { shell, intent: intentCtxFor(shell), drift: createDriftState(shell) };
    ctx = made;
    contexts.set(shell, made);
    /* A running analysis is tracked while no card is drawn too, as nothing drawn: a job that starts while the
       reader is on another page is never announced as one they watched begin. While a card is mounted its own
       commit tracks the board it drew, so the two never both run. */
    shell.runtime.store.subscribe(() => {
      if (made.drift.mountedCount() > 0) return;
      const data = shell.runtime.store.getSnapshot().data;
      if (data) trackJobs(made, data as unknown as Row, new Set());
    });
  }
  return ctx;
}

export function useDriftVersion(drift: DriftState): number {
  return useSyncExternalStore(drift.subscribe, drift.getVersion);
}
