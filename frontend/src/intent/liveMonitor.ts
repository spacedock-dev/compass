import { useEffect, useSyncExternalStore } from 'react';
import { isRecord, type Row } from '../observed';
import { identityOf } from './context';
import { endedAt } from '../observed/values';
import {
  answerMinutes,
  endNote,
  idleLease,
  parseLease,
  refusalNote,
  type EndReason,
  type LeaseState,
} from '../drift/monitor';
import { useShell, type Shell } from '../shell/context';

/* The Live monitor, as the page holds it. The server holds the lease, its clock and the Haiku level; this
   keeps only what this tab wants, whether its start was accepted, the last state the server told it, and
   the note an end left, all in memory. Nothing is written to storage, so a reload shows the switch off
   until it is pressed
   ([DEC-26](../../../docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)).
   Leaving the session ends it: a reader who comes back presses it again. */

/** The harnesses the monitor checks. Claude Code's only, as the server's `live_lease.HARNESS`. */
export const LIVE_HARNESSES: ReadonlySet<string> = new Set(['claude']);
/** The sample is view only and never takes a lease: it draws its estimate as though the switch were on. */
const SAMPLE = { harness: 'claude', sid: 'sample' } as const;
/** How often a tab says it is still here. The server lets a visible tab go quiet for 50 seconds. */
export const BEAT_MS = 20_000;

export interface MonitorEntry {
  /** This tab asked for the monitor on this session. */
  readonly wanted: boolean;
  /** The server accepted the start, so a later state saying it is off is an end. */
  readonly started: boolean;
  readonly lease: LeaseState | null;
  /** The page clock, in milliseconds, when `lease` was learned: the countdown runs from it. */
  readonly observedAt: number;
  /** The monitor ended for a reason that leaves the model-free estimate as the level (its limit, or a
      pause), so the estimate stays until the reader leaves or turns it on again. */
  readonly fallback: boolean;
  /** Why the monitor is off, in a sentence the Drift card shows; '' for none. */
  readonly note: string;
  /** The reason behind the note, so the question's banner can tell an end it caused from another. */
  readonly noteReason: EndReason | 'refused' | null;
}

const NONE: MonitorEntry = {
  wanted: false,
  started: false,
  lease: null,
  observedAt: 0,
  fallback: false,
  note: '',
  noteReason: null,
};
/* The sample starts with the level drawn, as it would after a reader turned the switch on, and the switch still
   shows and hides it. There is no lease behind it: nothing here is ever sent. */
const SAMPLE_ENTRY: MonitorEntry = { ...NONE, wanted: true };
/* Turning it on begins a new monitor: nothing of an earlier lease, its level, its question or its note carries in. */
const FRESH_START: Partial<MonitorEntry> = {
  wanted: true,
  started: false,
  lease: null,
  observedAt: 0,
  fallback: false,
  note: '',
  noteReason: null,
};
/* Leaving a session ends the wish and forgets the lease with it. */
const LEFT: Partial<MonitorEntry> = {
  wanted: false,
  started: false,
  lease: null,
  observedAt: 0,
  fallback: false,
};
const SAMPLE_KEY = `${SAMPLE.harness}:${SAMPLE.sid}`;

export interface MonitorStore {
  subscribe(listener: () => void): () => void;
  version(): number;
  get(key: string): MonitorEntry;
  update(key: string, patch: Partial<MonitorEntry>): void;
  /** A state the server published, kept when it is newer than the one held. */
  observe(key: string, lease: LeaseState): void;
  /** The lease ended: off, with the note for its reason, unless the reader turned it off themselves. */
  end(key: string, reason: EndReason, options?: { readonly answerMinutes?: number }): void;
  /** The start was refused. */
  refuse(key: string, why: string, lease: LeaseState | null): void;
}

const stores = new WeakMap<Shell, MonitorStore>();

export function liveMonitorFor(shell: Shell): MonitorStore {
  const store = stores.get(shell);
  if (store) return store;
  const entries = new Map<string, MonitorEntry>();
  const listeners = new Set<() => void>();
  let version = 0;
  const set = (key: string, next: MonitorEntry) => {
    entries.set(key, next);
    version += 1;
    for (const listener of [...listeners]) listener();
  };
  const made: MonitorStore = {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    version: () => version,
    get: (key) => entries.get(key) ?? (key === SAMPLE_KEY ? SAMPLE_ENTRY : NONE),
    update(key, patch) {
      const now = made.get(key);
      const next = { ...now, ...patch };
      if (
        (Object.keys(next) as (keyof MonitorEntry)[]).every((field) => next[field] === now[field])
      )
        return;
      set(key, next);
    },
    observe(key, lease) {
      const now = made.get(key);
      if (now.lease && lease.now < now.lease.now) return;
      if (now.lease && JSON.stringify(now.lease) === JSON.stringify(lease)) return;
      set(key, { ...now, lease, observedAt: shell.clock.now() });
    },
    end(key, reason, options = {}) {
      const now = made.get(key);
      if (!now.wanted && !now.started) return;
      set(key, {
        ...now,
        wanted: false,
        started: false,
        // A check that is paused or capped leaves the estimate as the level; every other end is an off.
        fallback: reason === 'cap' || reason === 'paused',
        note: endNote(reason, options),
        noteReason: reason,
      });
    },
    refuse(key, why, lease) {
      const now = made.get(key);
      set(key, {
        ...now,
        wanted: false,
        started: false,
        lease: lease ?? now.lease,
        observedAt: lease ? shell.clock.now() : now.observedAt,
        note: refusalNote(why),
        noteReason: 'refused',
      });
    },
  };
  stores.set(shell, made);
  return made;
}

export function monitorKey(session: Row): string {
  const identity = identityOf(session);
  return `${identity?.harness ?? ''}:${identity?.sid ?? ''}`;
}

export function isSampleSession(session: Row): boolean {
  const identity = identityOf(session);
  return identity?.harness === SAMPLE.harness && identity.sid === SAMPLE.sid;
}

/* Whether the switch is drawn for this session: a harness the monitor checks, with annotations on. */
export function liveMonitorShown(
  session: Readonly<Record<string, unknown>>,
  payload: Readonly<Record<string, unknown>>,
): boolean {
  return LIVE_HARNESSES.has(String(session['harness'] || '')) && payload['annotate'] === true;
}

/* Why the switch cannot be turned on, in the reader's words, or null. A session that has ended has nothing
   live to monitor; paused model calls and `--no-observer-model` refuse every check. */
export function monitorBlock(session: Row, payload: Row): string | null {
  if (endedAt(session) !== null) return 'The session has ended';
  const policy = isRecord(payload['reading']) ? payload['reading'] : null;
  if (policy?.['reason'] === 'run-disabled') return 'Model calls are off for this run';
  if (policy && (policy['off'] === true || policy['reason'] === 'model-calls-paused')) {
    return 'Model calls are paused';
  }
  return null;
}

export interface MonitorView {
  readonly shown: boolean;
  /** The switch reads on: this tab wants it, nothing blocks it, and (once known) the server holds it. */
  readonly on: boolean;
  readonly blocked: string | null;
  readonly lease: LeaseState;
  readonly note: string;
  readonly noteReason: MonitorEntry['noteReason'];
  readonly sample: boolean;
  press(on: boolean): void;
}

export function useMonitorEntry(session: Row): MonitorEntry {
  const store = liveMonitorFor(useShell());
  useSyncExternalStore(store.subscribe, store.version);
  return store.get(monitorKey(session));
}

/* What the switch, the Drift card and the question's banner read, from one place. The sample is always on, and
   never holds a lease. */
export function useLiveMonitor(session: Row, payload: Row): MonitorView {
  const shell = useShell();
  const store = liveMonitorFor(shell);
  const entry = useMonitorEntry(session);
  const key = monitorKey(session);
  const sample = isSampleSession(session);
  const blocked = sample ? null : monitorBlock(session, payload);
  return {
    shown: liveMonitorShown(session, payload),
    on: entry.wanted && blocked === null,
    blocked,
    lease: entry.lease ?? idleLease(),
    note: entry.note,
    noteReason: entry.noteReason,
    sample,
    press: (on) => {
      if (blocked !== null) return;
      store.update(key, on ? FRESH_START : { wanted: false });
    },
  };
}

/* Whether the live level is wanted for this session, for the Drift step that draws it. */
export function useLiveMonitorOn(session: Row): boolean {
  const entry = useMonitorEntry(session);
  return LIVE_HARNESSES.has(String(session['harness'] || '')) && (entry.wanted || entry.fallback);
}

/* The lease for a session the page is showing: start it when the reader turns the switch on, beat it while
   the tab is visible, say so once when the tab is hidden, and stop it when the reader turns it off, leaves
   the route or moves to another session. Mounted by the session view and nowhere else, and never for the
   sample. A page that goes away sends a stop beacon as well; the server does not depend on it, because a
   visible tab that stops beating is gone within 50 seconds. */
export function useLiveMonitorLease(session: Row, payload: Row): void {
  const shell = useShell();
  const store = liveMonitorFor(shell);
  const key = monitorKey(session);
  const identity = identityOf(session);
  const harness = identity?.harness ?? '';
  const sid = identity?.sid ?? '';
  const entry = useMonitorEntry(session);
  const supported = LIVE_HARNESSES.has(harness) && !isSampleSession(session) && Boolean(sid);
  const wanted = supported && entry.wanted;
  const blocked = supported ? monitorBlock(session, payload) : null;

  // Leaving this session, by unmount or by moving to another, ends the wish: a return finds it off.
  useEffect(() => {
    if (!supported) return undefined;
    return () => store.update(key, LEFT);
  }, [supported, store, key]);

  useEffect(() => {
    if (!wanted) return undefined;
    const { client } = shell.runtime;
    const { env } = shell;
    let started = false;
    let closed = false;
    // The server said the lease is gone, so there is nothing left to stop.
    let gone = false;
    let timer: unknown = null;
    // Aborts the beats only. The start is never aborted: a lease the server made after the reader had
    // gone has to be answered, and stopped.
    const abort = new AbortController();
    const body = (action: string, extra: Record<string, unknown> = {}) =>
      ({ harness, sid, tab_id: env.tabId, action, ...extra }) as never;
    const learn = (state: unknown) => {
      const parsed = parseLease(state);
      if (parsed) store.observe(key, parsed);
      return parsed;
    };
    const beat = (visible: boolean) => {
      void client.postLiveMonitor(body('beat', { visible }), abort.signal).then((result) => {
        if (closed || result.kind !== 'ok') return;
        const lease = learn(result.body.state);
        if (!result.body.ok) {
          gone = true;
          store.end(key, lease?.lastEnd?.reason ?? 'left', {
            answerMinutes: answerMinutes(lease),
          });
        }
      });
    };
    const startBeats = () => {
      // What is so now, at each beat: a tab can be hidden without the page having been told.
      if (timer === null) timer = env.clock.setInterval(() => beat(!env.isHidden()), BEAT_MS);
    };
    const stopBeats = () => {
      if (timer !== null) env.clock.clearInterval(timer);
      timer = null;
    };
    void client
      .postLiveMonitor(body('start', { observer_model: 1, visible: !env.isHidden() }))
      .then((result) => {
        if (result.kind === 'aborted') return;
        if (result.kind !== 'ok') {
          if (!closed) store.refuse(key, 'unreachable', null);
          return;
        }
        const lease = learn(result.body.state);
        if (closed) {
          // The reader had already gone: a lease the server just made must not outlive them.
          if (result.body.ok) void client.postLiveMonitor(body('stop'));
          return;
        }
        if (!result.body.ok) {
          store.refuse(key, result.body.reason, lease);
          return;
        }
        started = true;
        store.update(key, { started: true });
        // A tab hidden by now holds the lease without a visible cadence, and says so.
        if (env.isHidden()) beat(false);
        else startBeats();
      });
    const offHidden = env.onBecameHidden(() => {
      if (!started) return;
      stopBeats();
      beat(false);
    });
    const offVisible = env.onBecameVisible(() => {
      if (!started) return;
      beat(true);
      startBeats();
    });
    const offPageHide = env.onPageHide(() => {
      if (started) env.sendBeacon('/api/live-monitor', JSON.stringify(body('stop')));
    });
    return () => {
      closed = true;
      stopBeats();
      offHidden();
      offVisible();
      offPageHide();
      abort.abort();
      // Nothing to stop where the server has already told this tab the lease is off.
      if (started && !gone && store.get(key).lease?.on !== false) {
        void client.postLiveMonitor(body('stop'));
      }
    };
  }, [shell, store, key, harness, sid, wanted]);

  // The server says the lease is gone: off, with the note for why.
  const gone = wanted && entry.started && entry.lease !== null && !entry.lease.on;
  const lease = entry.lease;
  const reason = lease?.lastEnd?.reason;
  useEffect(() => {
    if (gone) store.end(key, reason ?? 'left', { answerMinutes: answerMinutes(lease) });
  }, [gone, reason, lease, store, key]);

  // The session ended while it was viewed, or model calls were paused: off, with the note.
  const blockedWhy = wanted ? blocked : null;
  useEffect(() => {
    if (!blockedWhy) return;
    store.end(key, endedAt(session) !== null ? 'ended' : 'paused');
  }, [blockedWhy, store, key, session]);
}
