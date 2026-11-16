import { nativeSession } from '../observed/native';
import { nextNumber } from '../api/bootstrap';
import { clock, isRecord, records, type Row } from '../observed/values';

/* The workstream evidence: what this tab has observed about each project's sessions changing state, plus
   what the server's history store replays for the time before the tab opened. Ported statement for
   statement from the legacy `next-workstream.js` (and the changes half of `nextObservedHistory`), and held
   to it by the differential test. Nothing here reads the DOM, the clock or a store: the evidence is a
   value, and a view that draws it hands it the payload that arrived.

   Two rules survive from the legacy file because a later reader will be tempted to tidy them:
   - A seeded record's LAST stored state closes a span rather than opening one. The store records what
     changed and never when the server stopped, so a final `working` record held to this tab's first
     payload would count a closed laptop as time an agent worked. Evidence is biased down, never invented.
   - Missing history is not zero. A project with no event in the window has an empty list and a caption
     that says how far back the evidence reaches, never a count of nothing. */

/** The most groups' entries one tab retains. 22 sessions at the five-second cadence make 95,040 samples in six hours. */
export const WORKSTREAM_ENTRY_CAP = 100_000;

/** What the caption says when nothing older than this tab is known. */
export const TAB_WINDOW = 'since this tab opened';

export interface WorkstreamSample {
  readonly at: number;
  readonly harness: string;
  readonly kind: 'sample';
  readonly project: string;
  readonly rate: number | null;
  readonly rateKnown: boolean;
  readonly sid: string;
  readonly state: string;
}

export interface WorkstreamEvent {
  readonly at: number;
  readonly filled: boolean;
  readonly fromState?: string;
  readonly harness: string;
  readonly kind: 'state' | 'turn' | 'ask';
  readonly label: string;
  readonly project: string;
  readonly right: string;
  readonly sid: string;
  readonly state?: string;
  readonly toState?: string;
}

interface Group {
  readonly at: number;
  events: readonly WorkstreamEvent[];
  samples: readonly WorkstreamSample[];
  weight: number;
}

export interface Batch {
  readonly at: number;
  readonly rows: readonly WorkstreamSample[];
}

export interface WorkstreamEvidence {
  readonly groups: readonly {
    readonly at: number;
    readonly events: readonly WorkstreamEvent[];
    readonly samples: readonly WorkstreamSample[];
  }[];
  readonly observedSince: number | null;
  readonly lastGenerated: number | null;
  readonly seeded: boolean;
  readonly seededSince: ReadonlyMap<string, number>;
}

export interface ProjectWindow {
  readonly batches: readonly Batch[];
  readonly endedAt: number | null;
  readonly events: readonly WorkstreamEvent[];
  readonly samples: readonly WorkstreamSample[];
  readonly seeded: boolean;
  readonly startedAt: number | null;
}

/** `${harness}:${sid}` with every falsy part empty: the delegation arithmetic keys its per-session state on it. */
export function sessionKey(
  session: { readonly harness?: unknown; readonly sid?: unknown } | null | undefined,
): string {
  return `${String(session?.harness || '')}:${String(session?.sid || '')}`;
}

interface SessionRead {
  readonly finishedAt: number | null;
  readonly harness: string;
  readonly project: string;
  readonly sid: string;
  readonly state: string;
}

function readSession(session: Row | null | undefined): SessionRead {
  session = session ? nativeSession(session) : session;
  return {
    finishedAt: nextNumber(session?.['finished_at']),
    harness: String(session?.['harness'] || ''),
    project: String(session?.['project'] || ''),
    sid: String(session?.['sid'] || ''),
    state: String(session?.['state'] || 'idle'),
  };
}

function harnessLabel(harness: unknown, labels: ReadonlyMap<unknown, unknown>): string {
  const fallback = String(harness || 'agent');
  return String(labels.get(fallback) || fallback).trim() || 'Agent';
}

export function stateLabel(state: string): string {
  if (state === 'working') return 'agent resumed';
  if (state === 'needs_input') return 'needs input';
  return 'became idle';
}

/** Whether a change is the reader's own turn: leaving a gate, or the first prompt after idle. */
export function transition(
  fromState: string | undefined,
  toState: string | undefined,
): { readonly filled: boolean; readonly humanTurn: boolean } {
  const leftGate = fromState === 'needs_input' && toState !== 'needs_input';
  const promptBoundary = fromState === 'idle' && toState === 'working';
  const humanTurn = leftGate || promptBoundary;
  return { filled: toState !== 'needs_input' && !humanTurn, humanTurn };
}

function rateKnown(
  harness: string,
  rate: number | null,
  sources: ReadonlyMap<string, Row>,
): boolean {
  if (rate === null) return false;
  const source = sources.get(harness);
  const fallback = rate > 0;
  if (!source) return fallback;
  if (source['error']) return false;
  return typeof source['reports_rate'] === 'boolean' ? source['reports_rate'] : fallback;
}

function askTime(ask: Row | undefined, generated: number, floor: number): number {
  const age = nextNumber(ask?.['age_sec']);
  if (age === null || age < 0) return generated;
  const registered = generated - age;
  return registered > floor && registered <= generated ? registered : generated;
}

/* Replays the history store's records as groups, oldest first, so a replayed window and a polled one are
   the same shape. Each record's own snapshot becomes a batch: every session known at that stamp, in the
   state its latest record gave it. The sample objects are shared between batches on purpose, since a
   full store is thousands of records and one object per session per record would allocate millions. */
function replay(
  history: unknown,
  labels: ReadonlyMap<unknown, unknown>,
  generated: number | null,
  append: (group: { at: number; events: WorkstreamEvent[]; samples: WorkstreamSample[] }) => void,
  seededSince: Map<string, number>,
): boolean {
  interface Stored {
    at: number;
    harness: string;
    project: string;
    sid: string;
    state: string;
  }
  const kept: Stored[] = [];
  for (const entry of Array.isArray(history) ? (history as unknown[]) : []) {
    const row = isRecord(entry) ? entry : undefined;
    const at = nextNumber(row?.['last_activity']);
    const sid = String(row?.['sid'] || '');
    // A record with no ordered stamp or no session cannot be placed on a timeline at all. The store is a
    // file any local process could have replaced, so this drops rather than repairs. A stamp past the
    // payload's own clock is dropped too. `at > null` is `at > 0` in the legacy comparison, so a payload
    // with no clock drops every positive stamp; that is kept rather than repaired.
    if (at === null || !sid || at > (generated ?? 0)) continue;
    kept.push({
      at,
      harness: String(row?.['harness'] || ''),
      project: String(row?.['project'] || ''),
      sid,
      state: String(row?.['state'] || 'idle'),
    });
  }
  if (kept.length === 0) return false;
  kept.sort((left, right) => left.at - right.at);
  const closes = new Map<string, number>();
  kept.forEach((record, index) => closes.set(sessionKey(record), index));
  const held = new Map<string, WorkstreamSample>();
  const seen = new Map<string, Stored>();
  kept.forEach((record, index) => {
    const key = sessionKey(record);
    if (!seededSince.has(record.project)) seededSince.set(record.project, record.at);
    const previous = seen.get(key);
    seen.set(key, record);
    if (closes.get(key) === index) {
      held.delete(key);
    } else {
      held.set(key, {
        at: record.at,
        harness: record.harness,
        kind: 'sample',
        project: record.project,
        // The store keeps no token rate, and an unknown rate is what turns the delegation figure into a
        // floor rather than a number it cannot support.
        rate: null,
        rateKnown: false,
        sid: record.sid,
        state: record.state,
      });
    }
    const events: WorkstreamEvent[] = [];
    if (previous && previous.state !== record.state) {
      const change = transition(previous.state, record.state);
      events.push({
        at: record.at,
        filled: change.filled,
        fromState: previous.state,
        harness: record.harness,
        kind: 'state',
        label: stateLabel(record.state),
        project: record.project,
        right: harnessLabel(record.harness, labels),
        sid: record.sid,
        state: record.state,
        toState: record.state,
      });
    }
    // A session's first stored record establishes the state a later change is measured against; it is not
    // itself a change, and listing it would make the rail's heading untrue of its own rows.
    append({ at: record.at, events, samples: [...held.values()] });
  });
  return true;
}

function harnessLabelMap(payload: Row): Map<unknown, unknown> {
  return new Map(records(payload['harnesses']).map((row) => [row['key'], row['label']]));
}

/* A payload-only derivation: the same replay in a private buffer, with the payload itself as the last
   observation. Used where no tab buffer exists (a differential comparison, a briefing built from one
   board); the live tab's buffer is `createWorkstream`. */
export function payloadEvidence(payload: Row): WorkstreamEvidence {
  const groups: WorkstreamEvidence['groups'][number][] = [];
  const seededSince = new Map<string, number>();
  const generated = nextNumber(payload['generated']);
  const seeded = replay(
    payload['history'],
    harnessLabelMap(payload),
    generated,
    (group) => groups.push(group),
    seededSince,
  );
  // `generated` is null for a payload with no clock, and the legacy group carries that null as its stamp.
  groups.push({ at: generated as number, samples: [], events: [] });
  return {
    groups,
    seededSince,
    seeded,
    lastGenerated: generated,
    observedSince: groups.length > 1 ? (groups[0] as { at: number }).at : generated,
  };
}

/* The tab's buffer. `observe` is called with every accepted payload and ignores one whose clock did not
   advance, so a repeat (StrictMode, a store notification for the same body) is a no-op. */
export function createWorkstream() {
  let groups: Group[] = [];
  let entryCount = 0;
  let previousSessions = new Map<string, SessionRead>();
  const seenAsks = new Map<string, number>();
  let lastGenerated: number | null = null;
  let observedSince: number | null = null;
  let seeded = false;
  let seededSince = new Map<string, number>();
  let version = 0;
  const listeners = new Set<() => void>();
  const changed = (): void => {
    version += 1;
    for (const listener of [...listeners]) listener();
  };

  function appendGroup(group: {
    at: number;
    events: readonly WorkstreamEvent[];
    samples: readonly WorkstreamSample[];
  }): void {
    // Empty advancing payloads still mark unknown time; one entry keeps them bounded.
    const weight = Math.max(1, group.samples.length + group.events.length);
    groups.push({ at: group.at, events: group.events, samples: group.samples, weight });
    entryCount += weight;
    while (entryCount > WORKSTREAM_ENTRY_CAP && groups.length > 1) {
      const removed = groups.shift() as Group;
      entryCount -= removed.weight;
    }
    if (entryCount <= WORKSTREAM_ENTRY_CAP) return;
    const retained = groups[0] as Group;
    const flat: (WorkstreamSample | WorkstreamEvent)[] = [
      ...retained.samples,
      ...retained.events,
    ].slice(entryCount - WORKSTREAM_ENTRY_CAP);
    retained.samples = flat.filter((entry): entry is WorkstreamSample => entry.kind === 'sample');
    retained.events = flat.filter((entry): entry is WorkstreamEvent => entry.kind !== 'sample');
    retained.weight = flat.length;
    entryCount = flat.length;
  }

  return {
    /** Whether the payload advanced the buffer. */
    observe(payload: unknown): boolean {
      const body: Row = isRecord(payload) ? payload : {};
      const generated = nextNumber(body['generated']);
      if (generated === null || (lastGenerated !== null && generated <= lastGenerated))
        return false;
      const sessions = records(body['sessions']);
      const asks = records(body['asks']);
      const labels = new Map<string, unknown>();
      const rateSources = new Map<string, Row>();
      for (const harness of records(body['harnesses'])) {
        const key = String(harness['key'] || '');
        if (key) {
          labels.set(key, String(harness['label'] || key));
          rateSources.set(key, harness);
        }
      }
      const current = new Map<string, SessionRead>();
      const samples: WorkstreamSample[] = [];
      for (const source of sessions) {
        const session = readSession(source);
        const key = sessionKey(session);
        if (!session.sid) continue;
        const rate = nextNumber(source['rate_per_min']);
        current.set(key, session);
        samples.push({
          at: generated,
          harness: session.harness,
          kind: 'sample',
          project: session.project,
          rate,
          rateKnown: rateKnown(session.harness, rate, rateSources),
          sid: session.sid,
          state: session.state,
        });
      }

      if (lastGenerated === null) {
        const since = new Map<string, number>();
        const replayed: Group[] = [];
        seeded = replay(
          body['history'],
          labels,
          generated,
          (group) => {
            replayed.push({ ...group, weight: 1 });
          },
          since,
        );
        seededSince = since;
        groups = [];
        entryCount = 0;
        for (const group of replayed) appendGroup(group);
        observedSince = groups.length > 0 ? (groups[0] as Group).at : generated;
        previousSessions = current;
        for (const ask of asks) {
          const id = String(ask['id'] || '');
          if (id) seenAsks.set(id, generated);
        }
        appendGroup({ at: generated, events: [], samples });
        lastGenerated = generated;
        changed();
        return true;
      }

      const events: WorkstreamEvent[] = [];
      for (const [key, session] of current) {
        const previous = previousSessions.get(key);
        if (!previous) continue;
        const right = harnessLabel(session.harness, labels);
        if (previous.state !== session.state) {
          const change = transition(previous.state, session.state);
          events.push({
            at: generated,
            filled: change.filled,
            fromState: previous.state,
            harness: session.harness,
            kind: 'state',
            label: stateLabel(session.state),
            project: session.project,
            right,
            sid: session.sid,
            state: session.state,
            toState: session.state,
          });
        }
        if (
          session.finishedAt !== null &&
          session.finishedAt > lastGenerated &&
          session.finishedAt <= generated &&
          (previous.finishedAt === null || session.finishedAt > previous.finishedAt)
        ) {
          events.push({
            at: session.finishedAt,
            filled: true,
            harness: session.harness,
            kind: 'turn',
            label: 'turn stopped',
            project: session.project,
            right,
            sid: session.sid,
          });
        }
      }
      for (const ask of asks) {
        const id = String(ask['id'] || '');
        if (!id || seenAsks.has(id)) continue;
        const at = askTime(ask, generated, lastGenerated);
        events.push({
          at,
          filled: false,
          harness: String(ask['harness'] || ''),
          kind: 'ask',
          label: String(ask['question'] || 'agent asked for input'),
          project: String(ask['project'] || ''),
          right: 'asked you',
          sid: String(ask['session_id'] || ''),
        });
        seenAsks.set(id, generated);
      }
      while (seenAsks.size > WORKSTREAM_ENTRY_CAP) {
        const oldest = seenAsks.keys().next().value;
        if (oldest === undefined) break;
        seenAsks.delete(oldest);
      }
      events.sort((left, right) => left.at - right.at);
      appendGroup({ at: generated, events, samples });
      previousSessions = current;
      lastGenerated = generated;
      changed();
      return true;
    },
    snapshot(): WorkstreamEvidence {
      return { groups, observedSince, lastGenerated, seeded, seededSince };
    },
    /** Changes with every accepted payload, so a view can subscribe to the buffer as it would to a store. */
    version: (): number => version,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export type Workstream = ReturnType<typeof createWorkstream>;

/* One project's slice of the evidence: its samples and events, the batches from its first appearance on,
   and how far back the evidence reaches. A project with nothing in the window starts where the tab did. */
export function projectWindow(project: string, evidence: WorkstreamEvidence): ProjectWindow {
  const batches: Batch[] = [];
  const samples: WorkstreamSample[] = [];
  const events: WorkstreamEvent[] = [];
  let startedAt: number | null = null;
  for (const group of evidence.groups) {
    const groupSamples = group.samples.filter((sample) => sample.project === project);
    const groupEvents = group.events.filter((event) => event.project === project);
    if ((groupSamples.length > 0 || groupEvents.length > 0) && startedAt === null) {
      startedAt = group.at;
    }
    if (startedAt !== null) batches.push({ at: group.at, rows: groupSamples });
    samples.push(...groupSamples);
    events.push(...groupEvents);
  }
  const observed = startedAt === null ? evidence.observedSince : startedAt;
  const seededAt = evidence.seededSince.get(project);
  return {
    batches,
    endedAt: evidence.lastGenerated,
    events,
    samples,
    seeded: evidence.seeded,
    startedAt:
      seededAt !== undefined && (observed === null || seededAt < observed) ? seededAt : observed,
  };
}

/* "last 3h 20m": how far back the window reaches. The days form is because the store's shipped
   retention is fourteen of them, and a seeded window reported as `last 336h` is a figure nobody reads as
   two weeks. */
export function windowLabel(window: Pick<ProjectWindow, 'startedAt' | 'endedAt'>): string {
  if (window.startedAt === null || window.endedAt === null || window.endedAt <= window.startedAt) {
    return TAB_WINDOW;
  }
  const seconds = Math.floor(window.endedAt - window.startedAt);
  if (seconds < 60) return `last ${String(Math.max(1, seconds))}s`;
  if (seconds < 3600) return `last ${String(Math.floor(seconds / 60))}m`;
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return minutes === 0 ? `last ${String(hours)}h` : `last ${String(hours)}h ${String(minutes)}m`;
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return hours === 0 ? `last ${String(days)}d` : `last ${String(days)}d ${String(hours)}h`;
}

export function windowPhrase(window: Pick<ProjectWindow, 'startedAt' | 'endedAt'>): string {
  const label = windowLabel(window);
  return label === TAB_WINDOW ? label : `in the ${label}`;
}

export interface Change {
  readonly at: string;
  readonly filled: boolean;
  readonly label: string;
  readonly harness: string;
  readonly kind: string;
}

export interface ProjectChanges {
  readonly changes: readonly Change[];
  /** "2 of 5 unattended · last 40m" */
  readonly noteText: string;
  /** "No state changes observed in the last 40m." */
  readonly emptyText: string;
}

export function projectChanges(window: ProjectWindow): ProjectChanges {
  const changes = window.events.map((event) => ({
    at: clock(event.at),
    filled: event.filled,
    label: event.label,
    harness: event.right,
    kind: event.kind,
  }));
  return {
    changes,
    noteText: `${String(changes.filter((change) => change.filled).length)} of ${String(changes.length)} unattended · ${windowLabel(window)}`,
    emptyText: `No state changes observed ${windowPhrase(window)}.`,
  };
}
