import { describe, expect, it } from 'vitest';
import { SAMPLE_FIXTURE } from './fixture';
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

  it('answers its context, its prompts and every page of its record, to its start', async () => {
    const context = await read(
      '/api/project-context?project=acme%2Fdashboard&session=claude%3Asample',
    );
    const prompts = await read(
      '/api/project-context?project=acme%2Fdashboard&session=claude%3Asample&prompts=1',
    );
    const stem = '/api/session-record?project=acme%2Fdashboard&session=claude%3Asample&limit=50';
    const newest = await read(stem);
    expect(context.body['semantic']).toBeDefined();
    expect(prompts.body['prompt_choices']).toBeDefined();
    expect((newest.body['entries'] as unknown[]).length).toBe(50);
    expect(newest.body).toMatchObject({ next: 'older-1', reached_start: false });
    const older = await read(`${stem}&before=older-1`);
    expect((older.body['entries'] as unknown[]).length).toBeGreaterThan(10);
    expect(older.body).toMatchObject({ next: null, reached_start: true });
    // A cursor the capture never issued is answered as unreadable, never as an empty start that would say
    // the cited entries do not exist.
    for (const cursor of ['x', 'toString', 'older-2'])
      expect((await read(`${stem}&before=${cursor}`)).body).toMatchObject({
        entries: [],
        state: 'stale',
        reached_start: false,
      });
  });

  it('answers every older page in order by the cursor the page before names', async () => {
    const stem = '/api/session-record?project=acme%2Fdashboard&session=claude%3Asample&limit=50';
    const seen: string[] = [];
    let url = stem;
    for (let step = 0; step < 5; step += 1) {
      const { body } = await read(url);
      seen.push(...(body['entries'] as { fact_id: string }[]).map((fact) => fact.fact_id));
      if (body['reached_start'] === true) break;
      url = `${stem}&before=${encodeURIComponent(String(body['next']))}`;
    }
    const pages = [SAMPLE_FIXTURE.record, ...Object.values(SAMPLE_FIXTURE.older ?? {})];
    const all = pages.flatMap((page) =>
      (page['entries'] as { fact_id: string }[]).map((fact) => fact.fact_id),
    );
    expect(seen).toEqual(all);
    expect(new Set(seen).size).toBe(seen.length);
  });

  it('composes the correction the real server composed, and accepts a copy', async () => {
    const composed = await read('/api/correction', { method: 'POST', body: '{}' });
    const copied = await read('/api/correction/copied', { method: 'POST', body: '{}' });
    expect(composed.body['ok']).toBe(true);
    expect(composed.body['parts']).toBeInstanceOf(Array);
    expect(copied.body).toEqual({ ok: true });
  });

  it.each([
    '/api/annotate',
    '/api/reading',
    '/api/direction',
    '/api/reading/cancel',
    '/api/focus',
    '/api/summary',
    '/api/summary/cancel',
    '/api/summary/delete',
  ])('refuses a write to %s and says why', async (path) => {
    const { status, body } = await read(path, { method: 'POST', body: '{}' });
    expect(status).toBe(403);
    expect(body).toMatchObject({ ok: false, reason: 'sample' });
  });
});
