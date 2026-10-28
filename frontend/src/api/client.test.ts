import { describe, expect, it, vi } from 'vitest';
import { createApiClient, fetchBounded, type FetchLike } from './client';

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function recorder(
  respond: (url: string, init: RequestInit | undefined) => Response | Promise<Response>,
) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetch: FetchLike = (url, init) => {
    calls.push({ url, init });
    return Promise.resolve(respond(url, init));
  };
  return { fetch, calls };
}

describe('GET /api/data', () => {
  it('returns the body with the revision header it carried', async () => {
    const { fetch, calls } = recorder(() =>
      json({ generated: 1, sessions: [] }, { headers: { 'X-Compass-Revision': '9.4' } }),
    );
    const result = await createApiClient({ fetch }).getData({ showAll: true, usage: true });
    expect(calls.map((call) => call.url)).toEqual(['/api/data?all=1&usage=1']);
    expect(result).toEqual({
      kind: 'ok',
      status: 200,
      body: { generated: 1, sessions: [] },
      revision: '9.4',
    });
  });

  it('reports a missing revision header as empty rather than guessing', async () => {
    const { fetch } = recorder(() => json({}));
    expect(
      await createApiClient({ fetch }).getData({ showAll: false, usage: false }),
    ).toMatchObject({ kind: 'ok', revision: '' });
  });

  it('keeps the status of a refusal apart from its body, including an HTML body', async () => {
    const html = recorder(
      () => new Response('<h1>403</h1>', { status: 403, headers: { 'Content-Type': 'text/html' } }),
    );
    expect(
      await createApiClient({ fetch: html.fetch }).getData({ showAll: false, usage: false }),
    ).toEqual({
      kind: 'http-error',
      status: 403,
      body: '<h1>403</h1>',
    });
    const jsonBody = recorder(() => json({ error: 'busy' }, { status: 503 }));
    expect(
      await createApiClient({ fetch: jsonBody.fetch }).getData({ showAll: false, usage: false }),
    ).toEqual({
      kind: 'http-error',
      status: 503,
      body: { error: 'busy' },
    });
  });

  it('never turns a failure into an empty healthy snapshot', async () => {
    const down = recorder(() => {
      throw new TypeError('network down');
    });
    const result = await createApiClient({ fetch: down.fetch }).getData({
      showAll: false,
      usage: false,
    });
    expect(result.kind).toBe('network-error');
    expect(result).not.toHaveProperty('body');
    const bad = recorder(() => new Response('not json', { status: 200 }));
    expect(
      await createApiClient({ fetch: bad.fetch }).getData({ showAll: false, usage: false }),
    ).toEqual({ kind: 'malformed', status: 200 });
    const array = recorder(() => json([1, 2]));
    expect(
      await createApiClient({ fetch: array.fetch }).getData({ showAll: false, usage: false }),
    ).toEqual({ kind: 'malformed', status: 200 });
  });

  it('reports an aborted request as aborted, not as a network failure', async () => {
    const controller = new AbortController();
    const { fetch } = recorder((_url, init) => {
      controller.abort();
      throw init?.signal?.reason ?? new Error('aborted');
    });
    expect(
      (
        await createApiClient({ fetch }).getData({
          showAll: false,
          usage: false,
          signal: controller.signal,
        })
      ).kind,
    ).toBe('aborted');
  });
});

describe('only GET /api/data reads the revision header', () => {
  it('leaves the revision empty on every other route', async () => {
    const { fetch } = recorder(() => json({}, { headers: { 'X-Compass-Revision': '1.1' } }));
    const client = createApiClient({ fetch });
    expect(await client.getProjectContext({ project: 'p' })).toMatchObject({
      kind: 'ok',
      revision: '',
    });
    expect(await client.getAnnotations({})).toMatchObject({ kind: 'ok', revision: '' });
  });
});

describe('/api/settings', () => {
  const body = {
    values: { analyze_listed_checks: 200 },
    limits: [{ key: 'analyze_listed_checks', default: 200, minimum: 12, maximum: 2000 }],
  };

  it('reads the settings in force with no query and no revision', async () => {
    const { fetch, calls } = recorder(() => json(body));
    const result = await createApiClient({ fetch }).getSettings();
    expect(calls.map((call) => [call.url, call.init?.method])).toEqual([
      ['/api/settings', undefined],
    ]);
    expect(result).toEqual({ kind: 'ok', status: 200, body, revision: '' });
  });

  it('posts the changed keys as JSON once, nulls included, and keeps a refusal as a refusal', async () => {
    const { fetch, calls } = recorder(
      () => new Response('<html>outside its bounds</html>', { status: 400 }),
    );
    const result = await createApiClient({ fetch }).postSettings({
      values: { analyze_listed_checks: 300, analyze_record_events: null },
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe('/api/settings');
    expect(calls[0]?.init?.method).toBe('POST');
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
      values: { analyze_listed_checks: 300, analyze_record_events: null },
    });
    expect(result).toEqual({
      kind: 'http-error',
      status: 400,
      body: '<html>outside its bounds</html>',
    });
  });
});

describe('GET /api/project-context', () => {
  it('encodes the stable project key and the exact session key', async () => {
    const { fetch, calls } = recorder(() => json({}));
    const client = createApiClient({ fetch });
    await client.getProjectContext({ project: '/repo/a b', session: 'claude:s:1' });
    await client.getProjectContext({ project: 'p' });
    await client.getProjectContext({
      project: 'p',
      session: 'codex:z',
      refresh: true,
      observerModel: true,
    });
    await client.getProjectContext({ project: 'p', session: 'codex:z', prompts: true });
    expect(calls.map((call) => call.url)).toEqual([
      '/api/project-context?project=%2Frepo%2Fa%20b&session=claude%3As%3A1',
      '/api/project-context?project=p',
      '/api/project-context?project=p&session=codex%3Az&refresh=1&observer_model=1',
      '/api/project-context?project=p&session=codex%3Az&prompts=1',
    ]);
  });
});

describe('POST adapters', () => {
  it('sends JSON once and never retries a failed action', async () => {
    const failing = recorder(() => {
      throw new TypeError('network down');
    });
    const client = createApiClient({ fetch: failing.fetch });
    const result = await client.postAnnotate({
      harness: 'claude',
      sid: 's',
      expected_revision: 2,
      add_direction: 'f1',
    });
    expect(result.kind).toBe('network-error');
    expect(failing.calls).toHaveLength(1);
    expect(failing.calls[0]?.init).toMatchObject({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    expect(JSON.parse(String(failing.calls[0]?.init?.body))).toEqual({
      harness: 'claude',
      sid: 's',
      expected_revision: 2,
      add_direction: 'f1',
    });
  });

  it('addresses each route at its own path', async () => {
    const { fetch, calls } = recorder(() => json({ ok: true }));
    const client = createApiClient({ fetch });
    const identity = { harness: 'claude', sid: 's' };
    await client.postDirection({ ...identity, fact_id: 'f' });
    await client.postReading({ ...identity, provider: 'claude', press: true, observer_model: 1 });
    await client.postReadingCancel({ ...identity, job: 'j', press: true, observer_model: 1 });
    await client.postGoalFind({ ...identity, provider: 'claude', press: true, observer_model: 1 });
    await client.postCorrection(identity);
    await client.postCorrectionCopied({ ...identity, text: 't' });
    await client.postTripwire({ action: 'save', id: 'r', stage: 'x', expected_revision: '' });
    await client.postLane({ supported: true, permission: 'granted' });
    await client.postAnswer({ id: 'a', index: 1 });
    await client.postSummary({ consent: 'off' });
    await client.postSummaryCancel(identity);
    await client.postSummaryDelete(identity);
    await client.postLiveMonitor({ ...identity, action: 'start', tab_id: 't', observer_model: 1 });
    expect(calls.map((call) => call.url)).toEqual([
      '/api/direction',
      '/api/reading',
      '/api/reading/cancel',
      '/api/goal/find',
      '/api/correction',
      '/api/correction/copied',
      '/api/tripwire',
      '/api/lane',
      '/api/answer',
      '/api/summary',
      '/api/summary/cancel',
      '/api/summary/delete',
      '/api/live-monitor',
    ]);
    expect(calls.every((call) => call.init?.method === 'POST')).toBe(true);
  });

  it('keeps a 409 and a 422 as http errors with their JSON bodies', async () => {
    const { fetch } = recorder(() => json({ ok: false, reason: 'not-running' }, { status: 409 }));
    expect(
      await createApiClient({ fetch }).postReadingCancel({
        harness: 'a',
        sid: 'b',
        job: 'j',
        press: true,
        observer_model: 1,
      }),
    ).toEqual({
      kind: 'http-error',
      status: 409,
      body: { ok: false, reason: 'not-running' },
    });
  });
});

describe('POST /api/focus', () => {
  const identity = { harness: 'claude', sid: 's' };
  const outcome = async (respond: () => Response, capability = 'cap') => {
    const { fetch, calls } = recorder(respond);
    const result = await createApiClient({ fetch }).focus({ identity, capability });
    return { result, calls };
  };

  it('sends nothing at all without a capability', async () => {
    for (const capability of ['', '   ']) {
      const { result, calls } = await outcome(() => json({ focused: true }), capability);
      expect(result).toBe('unavailable');
      expect(calls).toHaveLength(0);
    }
  });

  it('sends the pair and the capability header and reads the closed outcomes', async () => {
    const sent = await outcome(() => json({ focused: true }));
    expect(sent.result).toBe('sent');
    expect(sent.calls[0]?.init).toMatchObject({
      headers: { 'Content-Type': 'application/json', 'X-Compass-Capability': 'cap' },
    });
    expect(JSON.parse(String(sent.calls[0]?.init?.body))).toEqual(identity);
    expect((await outcome(() => json({ focused: false }))).result).toBe('declined');
    expect((await outcome(() => json({}, { status: 429 }))).result).toBe('throttled');
    expect((await outcome(() => json({}, { status: 403 }))).result).toBe('stale');
    expect((await outcome(() => json({}, { status: 503 }))).result).toBe('failed');
    expect((await outcome(() => new Response('<html>', { status: 200 }))).result).toBe('failed');
  });

  it('does not retry a network failure', async () => {
    const down = recorder(() => {
      throw new TypeError('down');
    });
    expect(
      await createApiClient({ fetch: down.fetch }).focus({ identity, capability: 'cap' }),
    ).toBe('failed');
    expect(down.calls).toHaveLength(1);
  });
});

describe('fetchBounded', () => {
  it('settles at the bound even when the fetch ignores the abort signal', async () => {
    const hostile: FetchLike = () => new Promise<Response>(() => undefined);
    const controller = new AbortController();
    const pending = fetchBounded(hostile, '/api/x', {}, controller.signal);
    controller.abort();
    await expect(pending).rejects.toThrow('bounded');
  });

  it('rejects at once when the signal is already aborted, without calling fetch', async () => {
    const fetch = vi.fn<FetchLike>();
    const controller = new AbortController();
    controller.abort();
    await expect(fetchBounded(fetch, '/api/x', {}, controller.signal)).rejects.toThrow('bounded');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('removes its abort listener on success and on failure', async () => {
    const controller = new AbortController();
    const add = vi.spyOn(controller.signal, 'addEventListener');
    const remove = vi.spyOn(controller.signal, 'removeEventListener');
    await fetchBounded(() => Promise.resolve(json({})), '/api/x', {}, controller.signal);
    await expect(
      fetchBounded(() => Promise.reject(new TypeError('x')), '/api/x', {}, controller.signal),
    ).rejects.toThrow('x');
    expect(add).toHaveBeenCalledTimes(2);
    expect(remove).toHaveBeenCalledTimes(2);
  });

  it('passes the signal to a cooperating fetch and runs unbounded without one', async () => {
    const seen: (AbortSignal | null | undefined)[] = [];
    const fetch: FetchLike = (_url, init) => {
      seen.push(init?.signal);
      return Promise.resolve(json({}));
    };
    const controller = new AbortController();
    await fetchBounded(fetch, '/api/x', {}, controller.signal);
    await fetchBounded(fetch, '/api/x', {}, undefined);
    expect(seen).toEqual([controller.signal, undefined]);
  });
});

describe('no adapter ever retries an action', () => {
  const identity = { harness: 'claude', sid: 's' };
  const adapters: Record<string, (client: ReturnType<typeof createApiClient>) => Promise<unknown>> =
    {
      postAnnotate: (c) => c.postAnnotate(identity),
      postDirection: (c) => c.postDirection({ ...identity, fact_id: 'f' }),
      postDirections: (c) => c.postDirections({ ...identity, fact_ids: ['f', 'g'] }),
      postReading: (c) =>
        c.postReading({ ...identity, provider: 'claude', press: true, observer_model: 1 }),
      postReadingCancel: (c) =>
        c.postReadingCancel({ ...identity, job: 'j', press: true, observer_model: 1 }),
      postGoalFind: (c) =>
        c.postGoalFind({ ...identity, provider: 'claude', press: true, observer_model: 1 }),
      postCorrection: (c) => c.postCorrection(identity),
      postCorrectionCopied: (c) => c.postCorrectionCopied({ ...identity, text: 't' }),
      postTripwire: (c) =>
        c.postTripwire({ action: 'save', id: 'r', stage: 's', expected_revision: '' }),
      postLane: (c) => c.postLane({ supported: true, permission: 'granted' }),
      postAnswer: (c) => c.postAnswer({ id: 'a', index: 0 }),
      postDismiss: (c) => c.postDismiss(identity),
      postNotify: (c) => c.postNotify({ message: 'm', session_id: 's' }),
      postSummary: (c) => c.postSummary({ ...identity, action: 'start', origin: 'open' }),
      postSummaryCancel: (c) => c.postSummaryCancel(identity),
      postSummaryDelete: (c) => c.postSummaryDelete(identity),
      postLiveMonitor: (c) =>
        c.postLiveMonitor({ ...identity, action: 'beat', tab_id: 't', visible: true }),
      postSettings: (c) => c.postSettings({ values: { analyze_listed_checks: null } }),
      focus: (c) => c.focus({ identity, capability: 'cap' }),
    };

  it('covers every POST adapter the client exposes', () => {
    const exposed = Object.keys(
      createApiClient({ fetch: () => Promise.reject(new Error('x')) }),
    ).filter((name) => name.startsWith('post') || name === 'focus');
    expect(Object.keys(adapters).sort()).toEqual(exposed.sort());
  });

  for (const [name, call] of Object.entries(adapters)) {
    it(`${name} makes exactly one fetch on a network failure and on an HTTP failure`, async () => {
      for (const failure of [
        () => Promise.reject(new TypeError('offline')),
        () => Promise.resolve(new Response('', { status: 503 })),
      ]) {
        const fetch = vi.fn<FetchLike>(failure);
        await call(createApiClient({ fetch }));
        expect(fetch).toHaveBeenCalledTimes(1);
      }
    });
  }
});

describe('settling', () => {
  it('reports aborted, not ok, when the signal aborts while the body is being read', async () => {
    const controller = new AbortController();
    const response = new Response('{"generated":1}', { status: 200 });
    Object.defineProperty(response, 'text', {
      value: () => {
        controller.abort();
        return Promise.resolve('{"generated":1}');
      },
    });
    const client = createApiClient({ fetch: () => Promise.resolve(response) });
    expect(
      (await client.getData({ showAll: false, usage: false, signal: controller.signal })).kind,
    ).toBe('aborted');
  });
});
