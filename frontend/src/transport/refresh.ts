import type { PayloadData } from '../api/types';
import type { DataFailure } from '../store/board';
import { revisionNewer, type RevisionMemo } from './revision';

export type DataOutcome =
  | { readonly kind: 'data'; readonly body: PayloadData; readonly revision: string }
  | { readonly kind: 'failed'; readonly failure: DataFailure }
  | { readonly kind: 'aborted' };

export interface RefreshSink {
  fetchData(signal: AbortSignal): Promise<DataOutcome>;
  /** A manual refresh is the only one that shows its own busy state. */
  manualInFlight(active: boolean): void;
  /** Store acceptance. Synchronous and separate from paint. */
  accepted(body: PayloadData, revision: string): void;
  failed(failure: DataFailure): void;
  /** Resolves when the consumer has shown the result, which it may hold back. */
  paint(info: {
    readonly manual: boolean;
    readonly accepted: boolean;
    /** A read that follows the run's own paint, such as the plan read after a poll. */
    readonly followUp?: boolean;
  }): Promise<void>;
}

type RunKind = 'call' | 'poll' | 'wake';

interface Run {
  readonly request: number;
  readonly manual: boolean;
  readonly kind: RunKind;
  waiters: (() => void)[];
}

interface Wanted {
  manual: boolean;
  waiters: (() => void)[];
  revision: string;
}

/* A save drew four GETs and painted on each, so there are three kinds of call.
   `refresh` is a reader's or a write's, and `poll` the boot's and the fallback
   poll's: each fetches at once and supersedes a fetch already out, whose answer
   is dropped, so a hung GET can never hold the board past the next poll.
   `wake` is the stream's and another tab's: it joins a fetch a write or a wake
   has out by queueing one more, and an answer that arrives with a run queued is
   dropped for it, never painted. A wake supersedes a poll's fetch, so a slow
   poll never delays the news. Either way an awaited `refresh()` resolves only
   after a fetch that STARTED AFTER THE CALL has painted: a superseded or
   dropped run hands its waiters on. A failure is counted only by the run that
   is still current, so an older request's failure never marks the board. */
export function createRefreshController(deps: {
  readonly sink: RefreshSink;
  readonly revisions: RevisionMemo;
}) {
  let latestRequest = 0;
  let active: Run | null = null;
  let wanted: Wanted | null = null;
  let manualInFlight = false;
  let disposed = false;
  const controllers = new Set<AbortController>();

  async function once(run: Run): Promise<boolean> {
    const controller = new AbortController();
    controllers.add(controller);
    if (run.manual) {
      manualInFlight = true;
      deps.sink.manualInFlight(true);
    }
    const stale = () => disposed || active !== run || wanted !== null;
    let accepted = false;
    try {
      const outcome = await deps.sink.fetchData(controller.signal);
      if (outcome.kind === 'aborted') return false;
      if (outcome.kind === 'failed') {
        if (stale()) return false;
        deps.sink.failed(outcome.failure);
      } else {
        /* A wake queued for a revision this answer already carries is answered
           by it: the announcement and this body are one collection. */
        const queued = wanted;
        if (
          active === run &&
          queued?.revision &&
          outcome.revision &&
          !revisionNewer(queued.revision, outcome.revision)
        ) {
          run.waiters.push(...queued.waiters);
          wanted = null;
        }
        if (stale()) return false;
        deps.revisions.advance(outcome.revision);
        deps.sink.accepted(outcome.body, outcome.revision);
        accepted = true;
      }
    } catch {
      if (stale()) return false;
      deps.sink.failed({ kind: 'malformed', status: 0 });
    } finally {
      controllers.delete(controller);
      if (run.manual) {
        manualInFlight = false;
        deps.sink.manualInFlight(false);
      }
    }
    try {
      await deps.sink.paint({ manual: run.manual, accepted });
    } catch {
      /* A consumer that fails to paint must not strand the waiters. */
    }
    return true;
  }

  function start(manual: boolean, waiters: (() => void)[], kind: RunKind): void {
    const run: Run = { request: ++latestRequest, manual, waiters, kind };
    if (active) {
      run.waiters.push(...active.waiters);
      active.waiters = [];
    }
    if (wanted) {
      // This run starts after every wake that queued one, so it answers them.
      run.waiters.push(...wanted.waiters);
      wanted = null;
    }
    active = run;
    void once(run).then((painted) => {
      if (painted) for (const done of run.waiters.splice(0)) done();
      if (active !== run) return;
      active = null;
      const queued = wanted;
      if (queued || run.waiters.length) {
        wanted = null;
        start(
          queued ? queued.manual : false,
          [...run.waiters.splice(0), ...(queued ? queued.waiters : [])],
          'wake',
        );
      }
    });
  }

  return {
    refresh(options: { readonly manual?: boolean } = {}): Promise<void> {
      const manual = options.manual === true;
      if (disposed || (manual && manualInFlight)) return Promise.resolve();
      return new Promise<void>((resolve) => start(manual, [resolve], 'call'));
    },
    poll(): Promise<void> {
      if (disposed) return Promise.resolve();
      return new Promise<void>((resolve) => start(false, [resolve], 'poll'));
    },
    /* `revision` is the one the wake announced, so a fetch already out whose
       answer carries it covers the wake and is painted rather than dropped. */
    wake(revision = ''): void {
      if (disposed) return;
      if (!active || active.kind === 'poll') {
        start(false, [], 'wake');
        return;
      }
      wanted ??= { manual: false, waiters: [], revision: '' };
      if (revision && revisionNewer(revision, wanted.revision)) wanted.revision = revision;
    },
    manualInFlight: (): boolean => manualInFlight,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const controller of controllers) controller.abort();
      for (const done of [...(active?.waiters ?? []), ...(wanted?.waiters ?? [])]) done();
      active = null;
      wanted = null;
    },
  };
}

export type RefreshController = ReturnType<typeof createRefreshController>;
