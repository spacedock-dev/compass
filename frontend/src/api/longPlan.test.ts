import { describe, expect, it } from 'vitest';
import { LONG_PLAN } from '../../test/longPlan';
import { longPlan, readingLongPlan } from './longPlan';
import { createApiClient } from './client';

describe('closed advisory long plan', () => {
  it('requires the exact successful envelope', () => {
    expect(readingLongPlan({ ok: true, long_plan: LONG_PLAN })).toEqual(LONG_PLAN);
    for (const value of [
      null,
      { ok: false, long_plan: LONG_PLAN },
      { ok: true, long_plan: LONG_PLAN, extra: 1 },
    ])
      expect(readingLongPlan(value)).toBeNull();
  });
  it('accepts only finite closed metadata and returns independent nested copies', () => {
    const accepted = longPlan(LONG_PLAN);
    expect(accepted).toEqual(LONG_PLAN);
    expect(accepted?.plan).not.toBe(LONG_PLAN.plan);
    for (const value of [
      null,
      { ...LONG_PLAN, extra: 'words' },
      { ...LONG_PLAN, version: true },
      { ...LONG_PLAN, binding: 'other' },
      { ...LONG_PLAN, plan: { ...LONG_PLAN.plan, max_calls: 18 } },
      { ...LONG_PLAN, source: { ...LONG_PLAN.source, parent_bytes: NaN } },
      { ...LONG_PLAN, measurements: { ...LONG_PLAN.measurements, retained_bytes: 'rss' } },
      { ...LONG_PLAN, allowance: { ...LONG_PLAN.allowance, reserved: true } },
      { ...LONG_PLAN, supported: false },
      { ...LONG_PLAN, prompt: { ...LONG_PLAN.prompt, fit_verified: true } },
    ])
      expect(longPlan(value)).toBeNull();
  });
  it('retains unknown counts and refuses malformed nonnull values', () => {
    const unknown = {
      ...LONG_PLAN,
      can_start: false,
      reason: 'allowance-unavailable',
      allowance: { ...LONG_PLAN.allowance, used: null, remaining: null, state: 'unknown' },
      source: { ...LONG_PLAN.source, parent_bytes: null, observed_at: null },
    };
    expect(longPlan(unknown)?.source.parent_bytes).toBeNull();
    expect(longPlan({ ...unknown, allowance: { ...unknown.allowance, used: false } })).toBeNull();
  });
  it('GETs the explicit session only without a request body or POST', async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const client = createApiClient({
      fetch: async (url, init) => {
        calls.push([url, init]);
        return new Response(JSON.stringify({ ok: true, long_plan: LONG_PLAN }));
      },
    });
    const answer = await client.getReadingLongPlan({ harness: 'claude', sid: 'a b' });
    expect(answer.kind).toBe('ok');
    expect(calls).toEqual([['/api/reading-long-plan?harness=claude&sid=a%20b', undefined]]);
  });
});
