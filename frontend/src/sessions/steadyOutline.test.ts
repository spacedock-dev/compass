// @vitest-environment jsdom
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ContextEntry } from '../store/board';
import { useSteadyOutline } from './steadyOutline';

const entry = (outline: unknown, plan: unknown = null, revision = 1): ContextEntry =>
  ({
    data: { sources: { outline, summary: { state: 'absent', plan } } },
    revision,
    error: null,
  }) as unknown as ContextEntry;

const sources = (value: ContextEntry | undefined) =>
  (value?.data as unknown as { sources: Record<string, { state?: string; plan?: unknown }> })
    .sources;

describe('a stale outline read', () => {
  it('keeps the last good outline and plan for the same session', () => {
    const ok = { state: 'ok', blocks: [{ span: { first: 'p1' } }] };
    const { result, rerender } = renderHook(
      ({ value, key }: { value: ContextEntry; key: string }) => useSteadyOutline(value, key),
      { initialProps: { value: entry(ok, { parts: 2 }), key: 'a' } },
    );
    expect(sources(result.current)['outline']).toBe(ok);
    rerender({ value: entry({ state: 'stale', blocks: [] }, null, 2), key: 'a' });
    expect(sources(result.current)['outline']).toBe(ok);
    expect(sources(result.current)['summary']?.plan).toEqual({ parts: 2 });
    expect(result.current?.revision).toBe(2);
    /* Another session never borrows this one's outline. */
    const other = entry({ state: 'stale', blocks: [] }, null, 3);
    rerender({ value: other, key: 'b' });
    expect(result.current).toBe(other);
  });
});
