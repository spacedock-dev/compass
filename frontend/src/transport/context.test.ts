import { describe, expect, it } from 'vitest';
import type { ApiResult, ProjectContext } from '../api/types';
import { createBoardStore } from '../store/board';
import { selectContextState, selectObserverRequest } from '../store/selectors';
import { createContextLoader } from './context';
import type { Consent } from './ports';

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => (resolve = done));
  return { promise, resolve };
}

const flush = async () => {
  for (let turn = 0; turn < 6; turn += 1) await Promise.resolve();
};

const okContext = (body: ProjectContext): ApiResult<ProjectContext> => ({
  kind: 'ok',
  status: 200,
  body,
  revision: '',
});
const offer = (enabled = true, disclosure = 'Sends prose to a model.'): ProjectContext => ({
  observer_model: { enabled, disclosure },
});

const FOCUS = { harness: 'claude', sid: 's:1' };
const PROJECT = { projectKey: '/repo/a', focus: null };
const FOCUSED = { projectKey: '/repo/a', focus: FOCUS };

function setup(_consent: Consent = null) {
  const board = createBoardStore({ now: () => 1 });
  const calls: {
    query: Parameters<ReturnType<typeof clientStub>['getProjectContext']>[0];
    answer: Deferred<ApiResult<ProjectContext>>;
  }[] = [];
  const clientStub = () => ({
    getProjectContext(query: {
      project: string;
      session?: string;
      refresh?: boolean;
      observerModel?: boolean;
      signal?: AbortSignal;
    }) {
      const answer = deferred<ApiResult<ProjectContext>>();
      calls.push({ query, answer });
      return answer.promise;
    },
  });
  const loader = createContextLoader({
    client: clientStub(),
    store: board,
  });
  return { board, calls, loader };
}

function accept(board: ReturnType<typeof createBoardStore>, generated: number) {
  board.acceptData({ generated, sessions: [] }, '');
}

describe('passive context reads', () => {
  it('reads nothing before the board has data', () => {
    const { loader, calls } = setup();
    loader.load(PROJECT);
    expect(calls).toHaveLength(0);
  });

  it('asks for the stable project key and the exact session key', () => {
    const { loader, calls, board } = setup();
    accept(board, 10);
    loader.load(FOCUSED);
    loader.load(PROJECT);
    expect(calls.map((call) => call.query)).toMatchObject([
      { project: '/repo/a', session: 'claude:s:1' },
      { project: '/repo/a' },
    ]);
    expect(calls[1]?.query.session).toBeUndefined();
    expect(calls[0]?.query.refresh).toBeUndefined();
    expect(calls[0]?.query.observerModel).toBeUndefined();
  });

  it('joins a request already out and reads again only for a newer generation', async () => {
    const { loader, calls, board } = setup();
    accept(board, 10);
    loader.load(FOCUSED);
    loader.load(FOCUSED);
    expect(calls).toHaveLength(1);
    calls[0]?.answer.resolve(okContext({}));
    await flush();
    expect(selectContextState(board.getSnapshot(), '/repo/a\nclaude:s:1')).toBe('ready');
    loader.load(FOCUSED);
    expect(calls).toHaveLength(1);
    accept(board, 11);
    loader.load(FOCUSED);
    expect(calls).toHaveLength(2);
  });

  it('keeps previous data beside a new failure and does not retry inside one generation', async () => {
    const { loader, calls, board } = setup();
    accept(board, 10);
    loader.load(PROJECT);
    calls[0]?.answer.resolve(okContext({ observers: [] }));
    await flush();
    accept(board, 11);
    loader.load(PROJECT);
    calls[1]?.answer.resolve({ kind: 'http-error', status: 503, body: '<html>' });
    await flush();
    const entry = board.getSnapshot().contexts.get('/repo/a\n');
    expect(entry).toEqual({
      data: { observers: [] },
      revision: 11,
      error: { kind: 'http-error', status: 503 },
    });
    expect(selectContextState(board.getSnapshot(), '/repo/a\n')).toBe('stale');
    loader.load(PROJECT);
    expect(calls).toHaveLength(2);
  });

  it('records each failure kind for a context that never loaded', async () => {
    const results: ApiResult<ProjectContext>[] = [
      { kind: 'http-error', status: 403, body: null },
      { kind: 'network-error' },
      { kind: 'malformed', status: 200 },
    ];
    const seen: unknown[] = [];
    for (const result of results) {
      const { loader, calls, board } = setup();
      accept(board, 10);
      loader.load(PROJECT);
      calls[0]?.answer.resolve(result);
      await flush();
      seen.push(board.getSnapshot().contexts.get('/repo/a\n')?.error);
      expect(selectContextState(board.getSnapshot(), '/repo/a\n')).toBe('unavailable');
    }
    expect(seen).toEqual([
      { kind: 'http-error', status: 403 },
      { kind: 'network-error' },
      { kind: 'malformed', status: 200 },
    ]);
  });

  it('keeps project and session scopes in separate entries', async () => {
    const { loader, calls, board } = setup();
    accept(board, 10);
    loader.load(FOCUSED);
    loader.load({ projectKey: '/repo/b', focus: FOCUS });
    calls[0]?.answer.resolve(okContext({}));
    await flush();
    expect(selectContextState(board.getSnapshot(), '/repo/a\nclaude:s:1')).toBe('ready');
    expect(selectContextState(board.getSnapshot(), '/repo/b\nclaude:s:1')).toBe('absent');
    expect(selectContextState(board.getSnapshot(), '/repo/a\n')).toBe('absent');
  });

  it('aborts its owned requests on dispose and writes nothing afterwards', async () => {
    const { loader, calls, board } = setup();
    accept(board, 10);
    loader.load(PROJECT);
    loader.dispose();
    expect(calls[0]?.query.signal?.aborted).toBe(true);
    calls[0]?.answer.resolve(okContext({}));
    await flush();
    expect(board.getSnapshot().contexts.size).toBe(0);
    loader.load(PROJECT);
    expect(calls).toHaveLength(1);
  });
});

describe('explicit observer summary', () => {
  async function withOffer(consent: Consent, model: ProjectContext = offer()) {
    const s = setup(consent);
    accept(s.board, 10);
    s.loader.load(FOCUSED);
    s.calls[0]?.answer.resolve(okContext(model));
    await flush();
    return s;
  }

  it('sends nothing without an enabled offer, a disclosure and a focused session', async () => {
    for (const [consent, model, scope] of [
      ['granted', offer(false), FOCUSED],
      ['granted', offer(true, ''), FOCUSED],
      ['granted', {}, FOCUSED],
      ['granted', offer(), PROJECT],
    ] as const) {
      const s = await withOffer(consent, model);
      await s.loader.requestObserverSummary(scope);
      expect(s.calls, `${String(consent)} ${JSON.stringify(model)}`).toHaveLength(1);
    }
  });

  it.each([null, 'declined'] as const)(
    'requests a summary without using the retired browser answer (%s)',
    async (answer) => {
      const s = await withOffer(answer);
      const pending = s.loader.requestObserverSummary(FOCUSED);
      expect(s.calls).toHaveLength(2);
      s.calls[1]?.answer.resolve(okContext(offer()));
      await pending;
    },
  );

  it('reads the focused session with refresh and observer_model, and records ready', async () => {
    const s = await withOffer('granted');
    const pending = s.loader.requestObserverSummary(FOCUSED);
    expect(s.calls[1]?.query).toMatchObject({
      project: '/repo/a',
      session: 'claude:s:1',
      refresh: true,
      observerModel: true,
    });
    expect(selectObserverRequest(s.board.getSnapshot(), '/repo/a\nclaude:s:1')).toEqual({
      pending: true,
      state: null,
    });
    s.calls[1]?.answer.resolve(
      okContext({ ...offer(), observers: [{ harness: 'claude', sid: 's:1', goal: 'ship' }] }),
    );
    await pending;
    const entry = s.board.getSnapshot().contexts.get('/repo/a\nclaude:s:1');
    expect(entry?.data?.observers?.[0]?.goal).toBe('ship');
    expect(entry?.error).toBeNull();
    expect(selectObserverRequest(s.board.getSnapshot(), '/repo/a\nclaude:s:1')).toEqual({
      pending: false,
      state: 'ready',
    });
  });

  it('records error and keeps the previous context when the request fails', async () => {
    const s = await withOffer('granted');
    const pending = s.loader.requestObserverSummary(FOCUSED);
    s.calls[1]?.answer.resolve({ kind: 'http-error', status: 503, body: null });
    await pending;
    expect(selectObserverRequest(s.board.getSnapshot(), '/repo/a\nclaude:s:1')).toEqual({
      pending: false,
      state: 'error',
    });
    expect(s.board.getSnapshot().contexts.get('/repo/a\nclaude:s:1')?.data).toEqual(offer());
  });

  it('allows one request per key at a time', async () => {
    const s = await withOffer('granted');
    void s.loader.requestObserverSummary(FOCUSED);
    await s.loader.requestObserverSummary(FOCUSED);
    expect(s.calls).toHaveLength(2);
  });

  it('suppresses the passive read while the explicit one is out', async () => {
    const s = await withOffer('granted');
    void s.loader.requestObserverSummary(FOCUSED);
    accept(s.board, 11);
    s.loader.load(FOCUSED);
    expect(s.calls).toHaveLength(2);
  });

  it('keeps a passive result that raced the explicit request from overwriting it', async () => {
    const s = setup('granted');
    accept(s.board, 10);
    s.loader.load(FOCUSED);
    s.calls[0]?.answer.resolve(okContext(offer()));
    await flush();
    accept(s.board, 11);
    s.loader.load(FOCUSED);
    expect(s.calls).toHaveLength(2);
    const explicit = s.loader.requestObserverSummary(FOCUSED);
    s.calls[2]?.answer.resolve(
      okContext({ ...offer(), observers: [{ harness: 'claude', sid: 's:1', goal: 'explicit' }] }),
    );
    await explicit;
    s.calls[1]?.answer.resolve(
      okContext({ ...offer(), observers: [{ harness: 'claude', sid: 's:1', goal: 'passive' }] }),
    );
    await flush();
    expect(
      s.board.getSnapshot().contexts.get('/repo/a\nclaude:s:1')?.data?.observers?.[0]?.goal,
    ).toBe('explicit');
  });

  it('never issues an observer request from a passive read, a repeat load or disposal', async () => {
    const s = await withOffer('granted');
    for (let generation = 11; generation < 15; generation += 1) {
      accept(s.board, generation);
      s.loader.load(FOCUSED);
    }
    s.loader.dispose();
    const refreshing = s.calls.filter((call) => call.query.refresh || call.query.observerModel);
    expect(refreshing).toHaveLength(0);
  });

  it('does not write after dispose', async () => {
    const s = await withOffer('granted');
    const pending = s.loader.requestObserverSummary(FOCUSED);
    s.loader.dispose();
    expect(s.calls[1]?.query.signal?.aborted).toBe(true);
    s.calls[1]?.answer.resolve(okContext({}));
    await pending;
    expect(selectObserverRequest(s.board.getSnapshot(), '/repo/a\nclaude:s:1').state).toBeNull();
  });
});

describe('freshness of a board body without a generation', () => {
  /* Legacy reads `nextFiniteNumber(nextData.generated)`, so a body with no
     `generated` is generation 0 and a settled read (revision 0) is never
     reread. The server always publishes `generated`; this pins that the port
     did not change the legacy default. */
  it('treats a missing generated as generation 0, as the legacy loader does', async () => {
    const { loader, calls, board } = setup();
    board.acceptData({ sessions: [] }, '');
    loader.load(PROJECT);
    calls[0]?.answer.resolve(okContext({}));
    await flush();
    expect(board.getSnapshot().contexts.get('/repo/a\n')?.revision).toBe(0);
    board.acceptData({ sessions: [] }, '');
    loader.load(PROJECT);
    expect(calls).toHaveLength(1);
    board.acceptData({ generated: 1, sessions: [] }, '');
    loader.load(PROJECT);
    expect(calls).toHaveLength(2);
  });
});
