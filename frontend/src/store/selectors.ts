import { payloadAsks, payloadSessions, type RowCollection } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import type { PayloadAsk, PayloadSession, ProjectContext, SessionIdentity } from '../api/types';
import type { BoardSnapshot, ContextEntry } from './board';

/* Every selector here is a pure function of one snapshot. Anything that builds
   a collection is memoised on the accepted body, so a subscriber that selects
   it gets the same object back until the data itself is replaced. */

const sessionsByBody = new WeakMap<object, RowCollection<PayloadSession>>();
const asksByBody = new WeakMap<object, RowCollection<PayloadAsk>>();
const harnessesByBody = new WeakMap<object, RowCollection<HarnessSource>>();
const NONE = { present: false, rows: [] } as const;

export function selectSessions(snapshot: BoardSnapshot): RowCollection<PayloadSession> {
  const body = snapshot.data;
  if (!body) return NONE;
  let cached = sessionsByBody.get(body);
  if (!cached) {
    cached = payloadSessions(body);
    sessionsByBody.set(body, cached);
  }
  return cached;
}

export function selectAsks(snapshot: BoardSnapshot): RowCollection<PayloadAsk> {
  const body = snapshot.data;
  if (!body) return NONE;
  let cached = asksByBody.get(body);
  if (!cached) {
    cached = payloadAsks(body);
    asksByBody.set(body, cached);
  }
  return cached;
}

/* The pair, not the sid alone: two harnesses can hold the same sid. */
export function selectSession(
  snapshot: BoardSnapshot,
  identity: SessionIdentity,
): PayloadSession | null {
  return (
    selectSessions(snapshot).rows.find(
      (row) => row.harness === identity.harness && row.sid === identity.sid,
    ) ?? null
  );
}

export type DataStatus = 'unread' | 'ready' | 'stale' | 'unavailable';

/* Unread is not unavailable, and a loaded board that failed its latest read is
   stale rather than empty: it still shows what was last accepted. */
export function selectDataStatus(snapshot: BoardSnapshot): DataStatus {
  if (snapshot.failures === 0) return snapshot.data ? 'ready' : 'unread';
  return snapshot.data ? 'stale' : 'unavailable';
}

export interface HarnessSource {
  readonly key: string;
  readonly label: string | null;
  /** null when the payload did not say, which is not the same as false. */
  readonly discovered: boolean | null;
  readonly error: string | null;
}

export function selectHarnessSources(snapshot: BoardSnapshot): RowCollection<HarnessSource> {
  const body = snapshot.data;
  if (!body || !Array.isArray(body.harnesses)) return NONE;
  let cached = harnessesByBody.get(body);
  if (!cached) {
    const rows = body.harnesses
      .filter((row) => typeof row === 'object' && row !== null && !Array.isArray(row))
      .map((row) => ({
        key: String(row.key ?? ''),
        label: typeof row.label === 'string' ? row.label : null,
        discovered: typeof row.discovered === 'boolean' ? row.discovered : null,
        error: typeof row.error === 'string' ? row.error : null,
      }));
    cached = { present: true, rows };
    harnessesByBody.set(body, cached);
  }
  return cached;
}

export type BuildStatus = 'unknown' | 'same' | 'reload-required';

export function selectBuildState(snapshot: BoardSnapshot): BuildStatus {
  const build = typeof snapshot.data?.build === 'string' ? snapshot.data.build : '';
  if (!snapshot.firstBuild || !build) return 'unknown';
  return build === snapshot.firstBuild ? 'same' : 'reload-required';
}

export type ContextState = 'absent' | 'pending' | 'ready' | 'stale' | 'unavailable';

export function contextEntryState(entry: ContextEntry | undefined): ContextState {
  if (!entry) return 'absent';
  if (entry.data) return entry.error ? 'stale' : 'ready';
  return entry.error ? 'unavailable' : 'pending';
}

export function selectContextState(snapshot: BoardSnapshot, key: string): ContextState {
  return contextEntryState(snapshot.contexts.get(key));
}

/* A finished failure outranks a read still in flight, which outranks data
   carried across a failure. `stale` shows as `ready` does: keeping the last
   known rows is a ruling, and saying so on screen would be unspecified copy. */
const READ_RANK: readonly ContextState[] = ['unavailable', 'absent', 'pending', 'stale', 'ready'];

export interface ContextRead {
  readonly state: ContextState;
  readonly entry: ContextEntry | undefined;
  readonly projectEntry: ContextEntry | undefined;
  readonly shows: boolean;
}

export function selectContextRead(
  snapshot: BoardSnapshot,
  projectKey: string,
  focus: SessionIdentity | null,
): ContextRead {
  const entry = snapshot.contexts.get(contextKey(projectKey, focus));
  const projectEntry = focus ? snapshot.contexts.get(contextKey(projectKey, null)) : entry;
  const states = [contextEntryState(entry)];
  if (focus) states.push(contextEntryState(projectEntry));
  const state = READ_RANK.find((candidate) => states.includes(candidate)) ?? 'absent';
  return { state, entry, projectEntry, shows: state === 'ready' || state === 'stale' };
}

export function selectObserverRequest(
  snapshot: BoardSnapshot,
  key: string,
): { readonly pending: boolean; readonly state: 'ready' | 'error' | null } {
  return {
    pending: snapshot.observer.requests.includes(key),
    state: snapshot.observer.states.get(key) ?? null,
  };
}

export function selectObserverModel(
  entry: ContextEntry | undefined,
): ProjectContext['observer_model'] | null {
  return entry?.data?.observer_model ?? null;
}

export function isPending(snapshot: BoardSnapshot, key: string): boolean {
  return snapshot.pending.includes(key);
}

export function selectReadingsOff(snapshot: BoardSnapshot): boolean {
  const policy = snapshot.data?.reading;
  return policy?.off === true || policy?.reason === 'model-calls-paused';
}

export function selectObserverOff(
  snapshot: BoardSnapshot,
  key: string,
  identity: SessionIdentity | null,
): boolean {
  // A goal answer can outlive Resume; the current master answer owns permission.
  if (typeof snapshot.data?.reading?.off === 'boolean') return selectReadingsOff(snapshot);
  return (
    selectReadingsOff(snapshot) ||
    snapshot.contexts
      .get(key)
      ?.data?.observers?.some(
        (row) =>
          row.harness === identity?.harness &&
          row.sid === identity?.sid &&
          row.model?.status === 'model-calls-paused',
      ) === true
  );
}
