import { nextFiniteNumber } from '../api/bootstrap';
import type { ApiClient } from '../api/client';
import { compatSessKey, contextKey } from '../api/identity';
import type { ApiFailure, SessionIdentity } from '../api/types';
import type { BoardStore, DataFailure } from '../store/board';
import { selectObserverOff } from '../store/selectors';

export interface ContextScope {
  /** The stable project key, never a label assumed unique. */
  readonly projectKey: string;
  /** The exact focused session, or null for the project-wide read. */
  readonly focus: SessionIdentity | null;
}

export interface ContextLoaderDeps {
  readonly client: Pick<ApiClient, 'getProjectContext'>;
  readonly store: BoardStore;
}

function failureOf(result: ApiFailure): DataFailure | null {
  switch (result.kind) {
    case 'http-error':
      return { kind: 'http-error', status: result.status };
    case 'malformed':
      return { kind: 'malformed', status: result.status };
    case 'network-error':
      return { kind: 'network-error' };
    case 'aborted':
      return null;
  }
}

/* Passive reads are source reading and spend nothing. The summary request is
   the one explicit action here: it needs an enabled offer and
   a published disclosure, and it never runs from a load, a reconnect or a
   disposal. A failed read keeps the previous data beside the new error rather
   than replacing it, which is why an entry carries both. */
export function createContextLoader(deps: ContextLoaderDeps) {
  const { client, store } = deps;
  const passive = new Map<string, object>();
  const observerRequests = new Set<string>();
  const controllers = new Set<AbortController>();
  let disposed = false;

  function controller(): AbortController {
    const owned = new AbortController();
    controllers.add(owned);
    return owned;
  }

  return {
    load(scope: ContextScope): void {
      const data = store.getSnapshot().data;
      if (disposed || !data) return;
      const key = contextKey(scope.projectKey, scope.focus);
      if (observerRequests.has(key)) return;
      const revision = nextFiniteNumber(data.generated);
      const settled = store.getSnapshot().contexts.get(key);
      if (passive.has(key) || (settled && settled.revision >= revision)) return;
      const token = {};
      passive.set(key, token);
      const owned = controller();
      void client
        .getProjectContext({
          project: scope.projectKey,
          ...(scope.focus ? { session: compatSessKey(scope.focus) } : {}),
          signal: owned.signal,
        })
        .then((result) => {
          controllers.delete(owned);
          if (disposed || passive.get(key) !== token) return;
          passive.delete(key);
          if (result.kind === 'ok') {
            store.setContext(key, { data: result.body, revision, error: null });
            return;
          }
          const error = failureOf(result);
          if (error) store.setContext(key, { data: settled?.data ?? null, revision, error });
        });
    },

    async requestObserverSummary(scope: ContextScope): Promise<void> {
      const { focus } = scope;
      const key = contextKey(scope.projectKey, focus);
      const model = store.getSnapshot().contexts.get(key)?.data?.observer_model;
      if (
        disposed ||
        !focus ||
        selectObserverOff(store.getSnapshot(), key, focus) ||
        model?.enabled !== true ||
        !model.disclosure ||
        observerRequests.has(key)
      ) {
        return;
      }
      observerRequests.add(key);
      store.setObserverRequest(key, true);
      // A passive read started before this explicit refresh must not replace its result.
      passive.delete(key);
      const owned = controller();
      try {
        const result = await client.getProjectContext({
          project: scope.projectKey,
          session: compatSessKey(focus),
          refresh: true,
          observerModel: true,
          signal: owned.signal,
        });
        if (disposed || result.kind === 'aborted') return;
        if (result.kind === 'ok') {
          store.setContext(key, {
            data: result.body,
            revision: nextFiniteNumber(store.getSnapshot().data?.generated),
            error: null,
          });
          store.setObserverState(key, 'ready');
        } else {
          store.setObserverState(key, 'error');
        }
      } finally {
        controllers.delete(owned);
        observerRequests.delete(key);
        store.setObserverRequest(key, false);
      }
    },

    dispose(): void {
      disposed = true;
      for (const owned of controllers) owned.abort();
      controllers.clear();
      passive.clear();
    },
  };
}

export type ContextLoader = ReturnType<typeof createContextLoader>;
