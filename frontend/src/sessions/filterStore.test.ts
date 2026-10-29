import { describe, expect, it } from 'vitest';
import type { Controls } from '../controls/kit';
import { EMPTY_FILTERS } from './filters';
import { filterStoreFor } from './filterStore';

const controls = () => ({}) as Controls;

describe('the filter store', () => {
  it('keeps one store per shell, so the sample session’s second shell holds its own', () => {
    const first = controls();
    expect(filterStoreFor(first)).toBe(filterStoreFor(first));
    expect(filterStoreFor(first)).not.toBe(filterStoreFor(controls()));
  });

  it('notifies on a change only, and never a listener that has left', () => {
    const store = filterStoreFor(controls());
    let heard = 0;
    const leave = store.subscribe(() => {
      heard += 1;
    });
    store.set(store.get());
    expect(heard).toBe(0);
    const next = { ...EMPTY_FILTERS, query: 'release' };
    store.set(next);
    expect(store.get()).toBe(next);
    expect(heard).toBe(1);
    store.reset();
    expect(store.get()).toBe(EMPTY_FILTERS);
    expect(heard).toBe(2);
    leave();
    store.set(next);
    expect(heard).toBe(2);
  });
});
