// @vitest-environment node
/* The client against the shared fixtures recorded from the real server
   (`frontend/test/fixtures/client-contract/`). The recorded status and body are
   the oracle: nothing here restates them. */
import { readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { createBoardStore } from '../store/board';
import {
  selectBuildState,
  selectDataStatus,
  selectHarnessSources,
  selectSession,
  selectSessions,
} from '../store/selectors';
import { createLiveTransport } from '../transport/live';
import { createRevisionMemo, revisionNewer } from '../transport/revision';
import { createFakeClock, createFakeEnvironment, createFakeStorageHub } from '../transport/testing';
import { expandExplanations } from './explanations';
import { createApiClient, type ApiClient, type FetchLike } from './client';
import type { ApiResult, FocusOutcome, PayloadData } from './types';

interface Fixture {
  readonly name: string;
  readonly request: {
    readonly method: string;
    readonly path: string;
    readonly query: string;
    readonly headers: Record<string, string>;
    readonly body: unknown;
  };
  readonly response: {
    readonly status: number;
    readonly headers: Record<string, string>;
    readonly body?: unknown;
    readonly text?: string;
    readonly error_page?: { readonly contains: readonly string[] };
  };
}

const DIRECTORY = new URL('../../test/fixtures/client-contract/', import.meta.url);

const fixtures: readonly Fixture[] = readdirSync(DIRECTORY)
  .filter((file) => file.endsWith('.json') && file !== 'index.json')
  .sort()
  .map((file) => JSON.parse(readFileSync(new URL(file, DIRECTORY), 'utf8')) as Fixture);

const byName = (name: string): Fixture => {
  const found = fixtures.find((fixture) => fixture.name === name);
  if (!found) throw new Error(`missing fixture ${name}`);
  return found;
};

function responseOf(fixture: Fixture): Response {
  const { status, headers } = fixture.response;
  if (fixture.response.body !== undefined)
    return new Response(JSON.stringify(fixture.response.body), { status, headers });
  if (fixture.response.error_page) {
    return new Response(
      `<html><body>${fixture.response.error_page.contains.join('\n')}</body></html>`,
      { status, headers },
    );
  }
  return new Response(fixture.response.text ?? '', { status, headers });
}

function replayOf(fixture: Fixture) {
  const sent: { url: string; init: RequestInit | undefined }[] = [];
  const fetch: FetchLike = (url, init) => {
    sent.push({ url, init });
    return Promise.resolve(responseOf(fixture));
  };
  return { sent, client: createApiClient({ fetch }) };
}

const query = (text: string) => [...new URLSearchParams(text).entries()];

function expectClassified(result: ApiResult<unknown>, fixture: Fixture): void {
  const { status } = fixture.response;
  if (status >= 200 && status < 300) {
    expect(result.kind).toBe('ok');
    if (result.kind === 'ok') {
      expect(result.status).toBe(status);
      expect(result.body).toEqual(expandExplanations(fixture.response.body));
    }
    return;
  }
  expect(result).toMatchObject({ kind: 'http-error', status });
  if (fixture.response.body !== undefined && result.kind === 'http-error')
    expect(result.body).toEqual(expandExplanations(fixture.response.body));
  if (fixture.response.error_page && result.kind === 'http-error') {
    // An error page is HTML: the status is kept and no JSON is invented for it.
    expect(typeof result.body).toBe('string');
    for (const needle of fixture.response.error_page.contains)
      expect(result.body).toContain(needle);
  }
}

type PostMethod = {
  [K in keyof ApiClient]: K extends `post${string}` ? K : never;
}[keyof ApiClient];

const POST_METHODS: Record<string, PostMethod> = {
  '/api/annotate': 'postAnnotate',
  '/api/direction': 'postDirection',
  '/api/reading': 'postReading',
  '/api/reading/cancel': 'postReadingCancel',
  '/api/correction': 'postCorrection',
  '/api/correction/copied': 'postCorrectionCopied',
  '/api/tripwire': 'postTripwire',
  '/api/lane': 'postLane',
  '/api/answer': 'postAnswer',
  '/api/dismiss': 'postDismiss',
  '/api/notify': 'postNotify',
};

describe('the fixture set is present', () => {
  it('holds the recorded scenarios the client contract needs', () => {
    expect(fixtures.length).toBeGreaterThanOrEqual(70);
    for (const name of [
      'data-healthy',
      'data-empty',
      'data-unavailable',
      'data-identity-collisions',
      'data-restarted-build',
      'focus-focused',
    ]) {
      expect(byName(name).name).toBe(name);
    }
  });
});

describe('every recorded GET answers as recorded', () => {
  const reads = fixtures.filter(
    (fixture) =>
      fixture.request.method === 'GET' &&
      /^\/api\/(data|annotations|project-context|session-record)$/.test(fixture.request.path),
  );

  it('covers data, annotations, project-context and session-record', () => {
    expect(new Set(reads.map((fixture) => fixture.request.path))).toEqual(
      new Set(['/api/data', '/api/annotations', '/api/project-context', '/api/session-record']),
    );
  });

  for (const fixture of reads) {
    it(`${fixture.name}: asks the recorded URL and classifies the recorded answer`, async () => {
      const { sent, client } = replayOf(fixture);
      const params = new URLSearchParams(fixture.request.query);
      const result =
        fixture.request.path === '/api/data'
          ? await client.getData({
              showAll: params.get('all') === '1',
              usage: params.get('usage') === '1',
            })
          : fixture.request.path === '/api/annotations'
            ? await client.getAnnotations({})
            : fixture.request.path === '/api/session-record'
              ? await client.getSessionRecord({
                  project: params.get('project') ?? '',
                  session: params.get('session') ?? '',
                  ...(params.has('limit') ? { limit: Number(params.get('limit')) } : {}),
                  ...(params.has('before') ? { before: params.get('before') as string } : {}),
                })
              : await client.getProjectContext({
                  project: params.get('project') ?? '',
                  ...(params.get('session') ? { session: params.get('session') as string } : {}),
                  prompts: params.get('prompts') === '1',
                  refresh: params.get('refresh') === '1',
                  observerModel: params.get('observer_model') === '1',
                });
      expect(sent).toHaveLength(1);
      const [path = '', search = ''] = (sent[0]?.url ?? '').split('?');
      expect(path).toBe(fixture.request.path);
      if (fixture.request.path !== '/api/project-context' || params.get('project')) {
        expect(query(search).sort()).toEqual(query(fixture.request.query).sort());
      }
      expectClassified(result, fixture);
      if (result.kind === 'ok') {
        expect(result.revision).toBe(
          fixture.request.path === '/api/data'
            ? (fixture.response.headers['X-Compass-Revision'] ?? '')
            : '',
        );
      }
    });
  }
});

describe('every recorded POST is sent once, as recorded, and answered as recorded', () => {
  const writes = fixtures.filter(
    (fixture) => fixture.request.method === 'POST' && fixture.request.path in POST_METHODS,
  );

  it('covers every action route the client adapts', () => {
    expect(new Set(writes.map((fixture) => fixture.request.path))).toEqual(
      new Set(
        Object.keys(POST_METHODS).filter(
          (path) => path !== '/api/tripwire' || writes.some((f) => f.request.path === path),
        ),
      ),
    );
  });

  for (const fixture of writes) {
    it(`${fixture.name}`, async () => {
      const { sent, client } = replayOf(fixture);
      const method = (
        fixture.request.path === '/api/direction' &&
        typeof fixture.request.body === 'object' &&
        fixture.request.body !== null &&
        'fact_ids' in fixture.request.body
          ? 'postDirections'
          : POST_METHODS[fixture.request.path]
      ) as PostMethod;
      const call = client[method] as (body: unknown) => Promise<ApiResult<unknown>>;
      const result = await call(fixture.request.body ?? {});
      expect(sent).toHaveLength(1);
      expect(sent[0]?.url).toBe(fixture.request.path);
      expect(sent[0]?.init?.method).toBe('POST');
      expect(JSON.parse(String(sent[0]?.init?.body))).toEqual(fixture.request.body ?? {});
      expectClassified(result, fixture);
    });
  }
});

describe('focus fixtures map to the closed outcomes', () => {
  const EXPECTED: Record<string, FocusOutcome> = {
    'focus-focused': 'sent',
    'focus-declined': 'declined',
    'focus-forbidden-capability': 'stale',
    'focus-throttled': 'throttled',
    'focus-disabled': 'failed',
    'focus-too-large': 'failed',
  };
  for (const [name, outcome] of Object.entries(EXPECTED)) {
    it(`${name} is ${outcome}`, async () => {
      const fixture = byName(name);
      const { sent, client } = replayOf(fixture);
      // The oversize request was recorded with no body: the 413 is the server's, not something the client builds.
      const identity = (fixture.request.body ?? { harness: 'claude', sid: 'a1b2c3d4' }) as {
        harness: string;
        sid: string;
      };
      expect(await client.focus({ identity, capability: 'present' })).toBe(outcome);
      expect(sent).toHaveLength(1);
      expect(sent[0]?.init?.headers).toMatchObject({ 'X-Compass-Capability': 'present' });
    });
  }

  it('sends nothing without a capability, which the server would refuse with 403', async () => {
    const fixture = byName('focus-missing-capability');
    expect(fixture.response.status).toBe(403);
    expect(fixture.request.headers).not.toHaveProperty('X-Compass-Capability');
    const { sent, client } = replayOf(fixture);
    expect(
      await client.focus({
        identity: fixture.request.body as { harness: string; sid: string },
        capability: '',
      }),
    ).toBe('unavailable');
    expect(sent).toHaveLength(0);
  });
});

function boardFrom(name: string) {
  const fixture = byName(name);
  const store = createBoardStore({ now: () => 1 });
  store.acceptData(
    fixture.response.body as PayloadData,
    fixture.response.headers['X-Compass-Revision'] ?? '',
  );
  return store;
}

describe('selectors over recorded boards', () => {
  it('reads healthy rows with the exact harness and sid they carry', () => {
    const rows = selectSessions(boardFrom('data-healthy').getSnapshot());
    expect(rows.present).toBe(true);
    expect(rows.rows.length).toBeGreaterThan(0);
    for (const row of rows.rows) {
      expect(typeof row.harness).toBe('string');
      expect(typeof row.sid).toBe('string');
    }
  });

  it('separates two harnesses that share a sid and a project label', () => {
    const snapshot = boardFrom('data-identity-collisions').getSnapshot();
    const rows = selectSessions(snapshot).rows;
    const shared = rows.filter((row) => row.sid === '0123abcd');
    expect(shared.map((row) => row.harness).sort()).toEqual(['claude', 'codex']);
    expect(selectSession(snapshot, { harness: 'codex', sid: '0123abcd' })?.harness).toBe('codex');
    expect(selectSession(snapshot, { harness: 'claude', sid: '0123abcd' })?.harness).toBe('claude');
    expect(selectSession(snapshot, { harness: 'gemini', sid: '0123abcd' })).toBeNull();
  });

  it('keeps an empty store distinct from an unreadable one', () => {
    const empty = boardFrom('data-empty').getSnapshot();
    const unavailable = boardFrom('data-unavailable').getSnapshot();
    expect(selectSessions(empty)).toEqual({ present: true, rows: [] });
    expect(selectSessions(unavailable)).toEqual({ present: true, rows: [] });
    expect(selectHarnessSources(empty).rows.every((row) => row.error === null)).toBe(true);
    const failing = selectHarnessSources(unavailable).rows.filter((row) => row.error !== null);
    expect(failing.map((row) => row.key)).toEqual(['claude']);
    expect(failing[0]?.discovered).toBe(true);
    expect(selectDataStatus(empty)).toBe('ready');
  });

  it('derives missing and malformed fields from the healthy body rather than assuming them', () => {
    const healthy = byName('data-healthy').response.body as PayloadData;
    const without = { ...healthy } as Record<string, unknown>;
    delete without['sessions'];
    const store = createBoardStore({ now: () => 1 });
    store.acceptData(without as PayloadData, '');
    expect(selectSessions(store.getSnapshot())).toEqual({ present: false, rows: [] });

    const mangled = {
      ...healthy,
      sessions: [null, 7, 'x', ...(healthy.sessions ?? [])],
    } as unknown as PayloadData;
    store.acceptData(mangled, '');
    expect(selectSessions(store.getSnapshot()).rows).toHaveLength(healthy.sessions?.length ?? -1);
  });

  it('flags the restarted build against the first one and sees its revision as newer', () => {
    const healthy = byName('data-healthy');
    const restarted = byName('data-restarted-build');
    const store = createBoardStore({ now: () => 1 });
    store.acceptData(
      healthy.response.body as PayloadData,
      healthy.response.headers['X-Compass-Revision'] ?? '',
    );
    expect(selectBuildState(store.getSnapshot())).toBe('same');
    store.acceptData(
      restarted.response.body as PayloadData,
      restarted.response.headers['X-Compass-Revision'] ?? '',
    );
    expect(selectBuildState(store.getSnapshot())).toBe('reload-required');
    expect(
      revisionNewer(
        restarted.response.headers['X-Compass-Revision'],
        healthy.response.headers['X-Compass-Revision'],
      ),
    ).toBe(true);
  });

  it('reports no revision when a proxy strips the header from a healthy answer', async () => {
    const fixture = byName('data-healthy');
    const stripped = new Response(JSON.stringify(fixture.response.body), { status: 200 });
    const client = createApiClient({ fetch: () => Promise.resolve(stripped) });
    expect(await client.getData({ showAll: false, usage: false })).toMatchObject({
      kind: 'ok',
      revision: '',
    });
  });
});

function frames(text: string): { event: string; data: string }[] {
  return text
    .split('\n\n')
    .map((block) => block.split('\n').filter((line) => line && !line.startsWith(':')))
    .filter((lines) => lines.length > 0)
    .map((lines) => ({
      event:
        lines
          .find((line) => line.startsWith('event:'))
          ?.slice(6)
          .trim() ?? 'message',
      data:
        lines
          .find((line) => line.startsWith('data:'))
          ?.slice(5)
          .trim() ?? '',
    }));
}

describe('stream fixtures through the live transport', () => {
  function liveTab() {
    const clock = createFakeClock();
    const hub = createFakeStorageHub();
    const env = createFakeEnvironment({ clock });
    const onWake = vi.fn<(revision: string) => void>();
    const live = createLiveTransport({
      env,
      storage: hub.forTab(),
      revisions: createRevisionMemo(),
      onWake,
      onPoll: vi.fn(),
    });
    live.start();
    return { env, onWake, live };
  }
  const deliver = (tab: ReturnType<typeof liveTab>, text: string) => {
    for (const frame of frames(text))
      if (frame.event === 'revision') tab.env.sources[0]?.emit('revision', frame.data);
  };

  it('wakes once for the initial revision and again for each newer one, including a restarted server', () => {
    const tab = liveTab();
    const initial = byName('stream-initial-revision').response.text ?? '';
    deliver(tab, initial);
    deliver(tab, initial);
    expect(tab.onWake).toHaveBeenCalledTimes(1);
    deliver(tab, byName('stream-revision-after-change').response.text ?? '');
    deliver(tab, byName('stream-restarted-build').response.text ?? '');
    expect(tab.onWake).toHaveBeenCalledTimes(3);
    tab.live.dispose();
  });
});
