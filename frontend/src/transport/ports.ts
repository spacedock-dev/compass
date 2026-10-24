import type { Lease } from '../storage/lease';

/* What the transport needs from its surroundings, as interfaces it owns. The
   production adapters live in `./browser.ts` and `../storage`; tests supply
   the doubles in `./testing.ts`. Nothing here touches a global. */

export type Consent = 'granted' | 'declined' | null;
export type ConsentAnswer = 'granted' | 'declined';

/** What the lease store read back, which a foreign or older record need not shape like a claim. */
export type { Lease } from '../storage/lease';

export interface LeaseClaim {
  readonly id: string;
  readonly ts: number;
}

/* Every operation may fail softly. A blocked store reads as null or false and
   never throws, because the transport's fallback is "each tab leads itself",
   not "stop". */
export interface TransportStorage {
  readLease(): Lease | null;
  /** False when storage cannot coordinate. */
  writeLease(claim: LeaseClaim): boolean;
  removeLease(): void;
  /** Written only for a revision the SSE stream announced. */
  writeRevision(revision: string): void;
  /** Another tab's announcement; never called for this tab's own write. */
  subscribeRevision(listener: (revision: string) => void): () => void;
  /** Valid storage wins, then this tab's own answer, then unanswered. */
  usageConsent(): Consent;
  setUsageConsent(answer: ConsentAnswer): void;
  observerConsent(): Consent;
  setObserverConsent(answer: ConsentAnswer): void;
}

export type TimerHandle = unknown;

export interface Clock {
  now(): number;
  setTimeout(callback: () => void, ms: number): TimerHandle;
  clearTimeout(handle: TimerHandle): void;
  setInterval(callback: () => void, ms: number): TimerHandle;
  clearInterval(handle: TimerHandle): void;
}

/** `readyState` follows EventSource: 0 connecting, 1 open, 2 closed. */
export interface EventSourceLike {
  readonly readyState: number;
  close(): void;
  addEventListener(
    type: 'error' | 'revision',
    listener: (event: { readonly data?: unknown }) => void,
  ): void;
}

export interface Environment {
  readonly tabId: string;
  readonly clock: Clock;
  readonly streamSupported: boolean;
  /** May throw; the transport tolerates it. */
  openStream(): EventSourceLike;
  onPageHide(listener: () => void): () => void;
  onBecameVisible(listener: () => void): () => void;
  /** Whether the tab is hidden now. */
  isHidden(): boolean;
  /** The tab went from visible to hidden. The Live monitor stops beating while it is. */
  onBecameHidden(listener: () => void): () => void;
  /** Fire and forget a JSON body as the page goes away. False where the browser has no beacon or refused it. */
  sendBeacon(url: string, body: string): boolean;
}
