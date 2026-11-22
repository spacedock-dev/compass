// @vitest-environment jsdom
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

it('clears filters without changing how the reader grouped the rows', () => {
  const store = filterStoreFor(controls());
  store.set({ ...EMPTY_FILTERS, byGroup: true, group: ['release'] });
  store.reset();
  expect(store.get().group).toEqual([]);
  expect(store.get().byGroup).toBe(true);
});

it('holds tab, search, and open filters in the same shell and resets in a new shell', async () => {
  const { act, fireEvent, screen, within } = await import('@testing-library/react');
  const { mountSessions } = await import('./testing');
  const { SIDS, sessionsSearchPayload } = await import('../../stories/sessionsSearch.fixture');
  const data = sessionsSearchPayload();
  const page = mountSessions({ data });
  await page.settle();
  const search = () => within(screen.getByRole('search', { name: 'Find sessions' }));
  const panel = () => search().getByRole('button', { name: 'Filters' });
  const worth = () => search().getByRole('button', { name: /^Worth a look/ });
  const input = () => search().getByRole('searchbox');
  fireEvent.click(worth());
  fireEvent.input(input(), { target: { value: 'release' } });
  fireEvent.click(panel());
  fireEvent.click(search().getByRole('button', { name: 'More filters for power users' }));
  await page.poll(data);
  act(() =>
    page.router.navigate({
      view: 'session',
      project: 'projects/pendulum-of-despair',
      harness: 'claude',
      session: SIDS.A,
    }),
  );
  await page.settle();
  expect(screen.queryByRole('search', { name: 'Find sessions' })).toBeNull();
  act(() => page.router.navigate({ view: 'sessions', project: null, session: null }));
  await page.settle();
  expect(worth().getAttribute('aria-pressed')).toBe('true');
  expect((input() as HTMLInputElement).value).toBe('release');
  expect(panel().getAttribute('aria-expanded')).toBe('true');
  expect(
    search()
      .getByRole('button', { name: 'More filters for power users' })
      .getAttribute('aria-expanded'),
  ).toBe('true');
  page.unmount();
  const fresh = mountSessions({ data });
  await fresh.settle();
  expect((input() as HTMLInputElement).value).toBe('');
  expect(panel().getAttribute('aria-expanded')).toBe('false');
  expect(worth().getAttribute('aria-pressed')).toBe('false');
});
