// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import type { FetchLike } from '../api/client';
import { githubPlan, readyPlan } from '../../test/plan-fixtures';
import { createBoardRuntime } from './runtime';
import { createFakeClock, createFakeEnvironment, createFakeStorageHub } from './testing';

const flush = async () => {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
};

type PlanAnswer = () => Promise<Response>;

/* A board that always answers and a plan read the test replaces between refreshes. */
function planRuntime(first: PlanAnswer) {
  const clock = createFakeClock();
  const env = createFakeEnvironment({ clock, streamSupported: true });
  const state = { plan: first };
  const fetch: FetchLike = (url) => {
    if (url === '/api/plan') return state.plan();
    return Promise.resolve(Response.json({ generated: 1, build: 'b1', sessions: [] }));
  };
  const paint = vi.fn((_info: { manual: boolean; accepted: boolean; followUp?: boolean }) =>
    Promise.resolve(),
  );
  const runtime = createBoardRuntime({
    fetch,
    storage: createFakeStorageHub().forTab(),
    env,
    search: '',
    doc: null,
    paint,
  });
  const read = async () => {
    await runtime.refresh({ manual: true });
    await flush();
  };
  return { clock, state, paint, runtime, read, plan: () => runtime.store.getSnapshot().plan };
}

const answer = (body: unknown, status = 200): PlanAnswer => {
  return () => Promise.resolve(new Response(JSON.stringify(body), { status }));
};
const ready = answer(readyPlan);

describe('the plan read', () => {
  it('leaves no tracker timers when teardown happens while a paint is pending', async () => {
    const { clock, paint, runtime, plan } = planRuntime(answer(githubPlan('refreshing')));
    paint.mockImplementation(({ followUp }) =>
      followUp ? new Promise<void>(() => undefined) : Promise.resolve(),
    );
    runtime.start();
    await flush();
    expect(plan()).toMatchObject({ state: 'ready' });
    runtime.dispose();
    expect(clock.activeTimers()).toBe(0);
  });

  it.each(['refreshing', 'retrying', 'ok'] as const)(
    'cancels a scheduled tracker read after %s on teardown',
    async (status) => {
      const fetchPlan = vi.fn(answer(githubPlan(status)));
      const { clock, runtime } = planRuntime(fetchPlan);
      runtime.start();
      await flush();
      expect(fetchPlan).toHaveBeenCalledTimes(1);
      const scheduled = clock.activeTimers();
      runtime.dispose();
      expect(clock.activeTimers()).toBe(0);
      expect(scheduled).toBeGreaterThan(2);
      clock.advance(30_000);
      await flush();
      expect(fetchPlan).toHaveBeenCalledTimes(1);
    },
  );

  it('keeps the tracker refusal and stops retrying after a follow-up fetch fails', async () => {
    const fetchPlan = vi.fn(answer(githubPlan('retrying')));
    const { clock, runtime, plan } = planRuntime(fetchPlan);
    try {
      runtime.start();
      await flush();
      expect(plan()).toMatchObject({
        state: 'ready',
        sources: [{ state: 'retrying', reason: 'signed-out' }],
      });
      expect(fetchPlan).toHaveBeenCalledTimes(1);

      fetchPlan.mockRejectedValueOnce(new Error('offline'));
      clock.advance(1_000);
      await flush();
      expect(plan()).toMatchObject({
        state: 'ready',
        sources: [{ state: 'refused', reason: 'signed-out' }],
      });
      expect(fetchPlan).toHaveBeenCalledTimes(2);

      clock.advance(1_000);
      await flush();
      expect(fetchPlan).toHaveBeenCalledTimes(2);
    } finally {
      runtime.dispose();
    }
  });

  it('starts unread, so a plan bookmark has nothing to fall back from yet', () => {
    const { plan } = planRuntime(ready);
    expect(plan()).toEqual({ state: 'unread' });
  });

  it.each([
    ['a server error', answer({ error: 'boom' }, 500)],
    ['a busy server', answer({ error: 'busy' }, 503)],
    ['a body that is not JSON', () => Promise.resolve(new Response('not json', { status: 200 }))],
    ['a network error', () => Promise.reject(new Error('offline'))],
    ['a ready body whose lane list is not a list', answer({ ...readyPlan, lanes: {} })],
    ['a ready body with no limits sentence', answer({ ...readyPlan, limits: null })],
  ] as const)('keeps the configured plan through %s', async (_name, failure) => {
    const { state, runtime, read, plan } = planRuntime(ready);
    runtime.start();
    await flush();
    const shown = plan();
    expect(shown).toMatchObject({ state: 'ready' });
    state.plan = failure;
    await read();
    expect(plan()).toBe(shown);
    runtime.dispose();
  });

  it('keeps the configured plan when a read times out', async () => {
    const { clock, state, runtime, plan } = planRuntime(ready);
    runtime.start();
    await flush();
    const shown = plan();
    state.plan = () => new Promise<Response>(() => undefined);
    void runtime.refresh({ manual: true });
    await flush();
    clock.advance(15_000);
    await flush();
    expect(plan()).toBe(shown);
    runtime.dispose();
  });

  it.each([
    ['not configured', answer({ state: 'not-configured' })],
    ['switched off', answer(null, 404)],
    ['loopback only', answer({ reason: 'loopback-only' }, 403)],
  ] as const)('clears the plan only when the server says it is %s', async (_name, absent) => {
    const { state, runtime, read, plan } = planRuntime(ready);
    runtime.start();
    await flush();
    state.plan = absent;
    await read();
    expect(plan()).toEqual({ state: 'none' });
    runtime.dispose();
  });

  it('marks a first read that failed as failed, not as no plan, and recovers on the next read', async () => {
    const { state, runtime, read, plan } = planRuntime(answer({}, 500));
    runtime.start();
    await flush();
    expect(plan()).toEqual({ state: 'failed' });
    state.plan = ready;
    await read();
    expect(plan()).toMatchObject({ state: 'ready' });
    runtime.dispose();
  });

  it('paints a plan change through the paint option, and an unchanged plan not at all', async () => {
    const { paint, runtime, read, plan } = planRuntime(ready);
    runtime.start();
    await flush();
    const shown = plan();
    const painted = paint.mock.calls.length;
    await read();
    // The manual refresh paints its board once; the identical plan neither replaces nor paints.
    expect(plan()).toBe(shown);
    expect(paint.mock.calls.length).toBe(painted + 1);
    runtime.dispose();
  });

  it('asks for a paint after a changed plan, marked manual only for a manual refresh', async () => {
    const { state, paint, runtime, read, plan } = planRuntime(answer({ state: 'not-configured' }));
    runtime.start();
    await flush();
    expect(plan()).toEqual({ state: 'none' });
    expect(paint).toHaveBeenLastCalledWith({ manual: false, accepted: true, followUp: true });
    state.plan = ready;
    await read();
    expect(plan()).toMatchObject({ state: 'ready' });
    expect(paint).toHaveBeenLastCalledWith({ manual: true, accepted: true, followUp: true });
    runtime.dispose();
  });

  it('keeps an ask whose words the settings keep off the board', async () => {
    const { runtime, plan } = planRuntime(
      answer({ ...readyPlan, asks: [{ ...readyPlan.asks[0], text: null }] }),
    );
    runtime.start();
    await flush();
    expect(plan()).toMatchObject({ state: 'ready', asks: [{ id: 'hours', text: null }] });
    runtime.dispose();
  });

  it.each([
    ['ask', 'asks', { id: 'broken' }],
    ['goal', 'goals', { id: 'x' }],
    ['lane', 'lanes', { id: 'x', title: 7 }],
    ['design note', 'design', { title: 'x' }],
    ['tracker row', 'tracker', null],
    ['diagram', 'diagrams', { title: 'x', caption: 'x' }],
    ['source', 'sources', { label: 'x', state: 'maybe' }],
  ] as const)(
    'drops one malformed %s and keeps the rest of the plan',
    async (_name, list, broken) => {
      const items = readyPlan[list] as readonly unknown[];
      const { runtime, plan } = planRuntime(answer({ ...readyPlan, [list]: [broken, ...items] }));
      runtime.start();
      await flush();
      const shown = plan();
      expect(shown).toMatchObject({ state: 'ready' });
      expect((shown as unknown as Record<string, unknown>)[list]).toEqual(items);
      runtime.dispose();
    },
  );
});
