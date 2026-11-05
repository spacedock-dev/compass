import { createApiClient } from './client';
import { describe, expect, it } from 'vitest';
import { LONG_HISTORY, HISTORY_ITEM } from '../../test/longHistory';
import { readingLongHistory, readingLongDiscard } from './longHistory';

describe('bounded recovery display projection', () => {
  it('uses explicit encoded session GET and exact acknowledged POST, preserving refusal status', async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const client = createApiClient({
      fetch: async (url, init) => {
        calls.push([url, init]);
        return new Response(
          JSON.stringify(
            init
              ? { ok: false, discarded: false, reason: 'marker-changed' }
              : { ok: true, long_history: LONG_HISTORY },
          ),
          { status: init ? 409 : 200 },
        );
      },
    });
    expect(calls).toEqual([]);
    await client.getReadingLongHistory({ harness: 'claude', sid: 'a b' });
    expect(calls[0]).toEqual(['/api/reading-long-history?harness=claude&sid=a%20b', undefined]);
    const request = {
      harness: 'claude',
      sid: 'a b',
      job: HISTORY_ITEM.job_id,
      press: true,
      observer_model: 1,
    } as const;
    const answer = await client.postReadingLongDiscard(request);
    expect(answer).toMatchObject({ kind: 'http-error', status: 409, body: { discarded: false } });
    expect(calls[1]?.[0]).toBe('/api/reading-long-discard');
    expect(JSON.parse(String(calls[1]?.[1]?.body))).toEqual(request);
  });

  it('reads exact, minimum and unknown without substituting zero', () => {
    const unknown = {
      ...HISTORY_ITEM,
      job_id: 'b'.repeat(32),
      accounting: 'unknown',
      exact: null,
      minimum: null,
      unsettled: null,
    };
    const minimum = { ...HISTORY_ITEM, job_id: 'c'.repeat(32), accounting: 'minimum', exact: null };
    expect(
      readingLongHistory({
        ok: true,
        long_history: {
          ...LONG_HISTORY,
          items: [HISTORY_ITEM, minimum, unknown],
          incomplete: true,
          reason: 'accounting-unavailable',
        },
      })?.items,
    ).toEqual([HISTORY_ITEM, minimum, unknown]);
  });
  it('rejects malformed, conflicting, duplicate and oversized inventories', () => {
    for (const items of [
      [{ ...HISTORY_ITEM, exact: null }],
      [{ ...HISTORY_ITEM, started_at: Infinity }],
      [{ ...HISTORY_ITEM, job_id: '../private' }],
      [{ ...HISTORY_ITEM, state: 'dead' }],
      [{ ...HISTORY_ITEM, minimum: { ...HISTORY_ITEM.minimum, calls: 3 } }],
      [{ ...HISTORY_ITEM, private_words: 'secret' }],
      [HISTORY_ITEM, HISTORY_ITEM],
      Array.from({ length: 129 }, (_, i) => ({
        ...HISTORY_ITEM,
        job_id: i.toString(16).padStart(32, '0'),
      })),
    ])
      expect(readingLongHistory({ ok: true, long_history: { ...LONG_HISTORY, items } })).toBeNull();
  });
  it('accepts actual removal with unresolved cleanup but never raw reasons or mismatched success', () => {
    expect(readingLongDiscard({ ok: true, discarded: true, reason: 'receipt-unresolved' })).toEqual(
      { ok: true, discarded: true, reason: 'receipt-unresolved' },
    );
    expect(
      readingLongDiscard({ ok: false, discarded: false, reason: 'owner-current' })?.discarded,
    ).toBe(false);
    for (const value of [
      { ok: true, discarded: false, reason: '' },
      { ok: false, discarded: false, reason: '/private/path' },
      { ok: true },
    ])
      expect(readingLongDiscard(value)).toBeNull();
  });
});
