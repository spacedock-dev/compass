import { describe, expect, it } from 'vitest';
import { SAMPLE_FIXTURE } from './fixture';
import { pagedSample } from './paged.testing';
import { createSampleFetch } from './sampleFetch';

const fetcher = createSampleFetch(SAMPLE_FIXTURE);
const read = async (url: string, init?: RequestInit) => {
  const reply = await fetcher(url, init);
  return { status: reply.status, body: (await reply.json()) as Record<string, unknown> };
};

describe('the sample session server', () => {
  it('answers the board with the one sample session', async () => {
    const { status, body } = await read('/api/data');
    const rows = body['sessions'] as { sid: string; harness: string }[];
    expect(status).toBe(200);
    expect(rows.map((row) => `${row.harness}:${row.sid}`)).toEqual(['claude:sample']);
  });

  it('answers its context, its prompts and its one page of record', async () => {
    const context = await read(
      '/api/project-context?project=acme%2Fdashboard&session=claude%3Asample',
    );
    const prompts = await read(
      '/api/project-context?project=acme%2Fdashboard&session=claude%3Asample&prompts=1',
    );
    const page = await read(
      '/api/session-record?project=acme%2Fdashboard&session=claude%3Asample&limit=50',
    );
    const older = await read(
      '/api/session-record?project=acme%2Fdashboard&session=claude%3Asample&limit=50&before=x',
    );
    expect(context.body['semantic']).toBeDefined();
    expect(prompts.body['prompt_choices']).toBeDefined();
    expect((page.body['entries'] as unknown[]).length).toBeGreaterThan(10);
    expect(page.body).toMatchObject({ next: null, reached_start: true });
    // The one page is the whole record, so an older-page request names a cursor the capture never issued.
    // It is answered as unreadable, never as an empty start that would say the cited entries do not exist.
    expect(older.body).toMatchObject({ entries: [], state: 'stale', reached_start: false });
  });

  it('answers every older page of a longer record, in order, to its start', async () => {
    const paged = createSampleFetch(pagedSample(SAMPLE_FIXTURE, 'oldest'));
    const stem = '/api/session-record?project=acme%2Fdashboard&session=claude%3Asample&limit=50';
    const seen: string[] = [];
    let url = stem;
    for (let step = 0; step < 5; step += 1) {
      const body = (await (await paged(url)).json()) as Record<string, unknown>;
      seen.push(...(body['entries'] as { fact_id: string }[]).map((fact) => fact.fact_id));
      if (body['reached_start'] === true) break;
      url = `${stem}&before=${encodeURIComponent(String(body['next']))}`;
    }
    const all = (SAMPLE_FIXTURE.record['entries'] as { fact_id: string }[]).map((f) => f.fact_id);
    expect(seen).toEqual(all);
    const unknown = (await (await paged(`${stem}&before=toString`)).json()) as Record<
      string,
      unknown
    >;
    expect(unknown).toMatchObject({ state: 'stale', entries: [] });
  });

  it('composes the correction the real server composed, and accepts a copy', async () => {
    const composed = await read('/api/correction', { method: 'POST', body: '{}' });
    const copied = await read('/api/correction/copied', { method: 'POST', body: '{}' });
    expect(composed.body['ok']).toBe(true);
    expect(composed.body['parts']).toBeInstanceOf(Array);
    expect(copied.body).toEqual({ ok: true });
  });

  it.each(['/api/annotate', '/api/reading', '/api/direction', '/api/reading/cancel', '/api/focus'])(
    'refuses a write to %s and says why',
    async (path) => {
      const { status, body } = await read(path, { method: 'POST', body: '{}' });
      expect(status).toBe(403);
      expect(body).toMatchObject({ ok: false, reason: 'sample' });
    },
  );
});
