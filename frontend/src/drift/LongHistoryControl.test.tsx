import { act, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HISTORY_ITEM, LONG_HISTORY } from '../../test/longHistory';
import { SAMPLE_FRAGMENT } from '../sample/ids';
import { json, mountDrift, press, driftBoard, POLICY } from './testing';

const GET = '/api/reading-long-history';
const POST = '/api/reading-long-discard';
const discard = () => screen.getByRole('button', { name: 'Check and discard superseded record' });
async function open(page: ReturnType<typeof mountDrift>) {
  await page.settle();
  expect(page.gets(GET)).toBe(0);
  await press(screen.getByRole('button', { name: 'Unfinished long analysis records' }));
  await page.settle();
}
describe('explicit unfinished history inspector', () => {
  for (const accounting of ['exact', 'minimum']) {
    it.each([0, 1, 2])(
      `uses the recorded call count's singular or plural for ${accounting} accounting: %i`,
      async (calls) => {
        const totals = { ...HISTORY_ITEM.minimum, calls };
        const item = {
          ...HISTORY_ITEM,
          accounting,
          exact: accounting === 'exact' ? totals : null,
          minimum: totals,
        };
        const page = mountDrift({
          routes: {
            [GET]: () =>
              json({
                ok: true,
                long_history: {
                  ...LONG_HISTORY,
                  items: [item],
                  incomplete: accounting !== 'exact',
                },
              }),
          },
        });
        await open(page);
        const caption = `${accounting === 'exact' ? 'Exact recorded accounting: ' : 'Minimum recorded accounting: at least '}${calls} ${calls === 1 ? 'call' : 'calls'};`;
        expect(screen.getByText((text) => text.startsWith(caption))).toBeTruthy();
        expect(page.posts(POST)).toBe(0);
      },
    );
  }

  it('stays cold across polling and reads only on opening or Refresh, even Paused and after Clear', async () => {
    const page = mountDrift({
      payload: { reading: { ...POLICY, off: true, remaining: 0 } },
      store: { goal: '', lines: [] },
      routes: { [GET]: () => json({ ok: true, long_history: LONG_HISTORY }) },
    });
    await page.settle();
    await page.poll(
      driftBoard({
        payload: { reading: { ...POLICY, off: true, remaining: 0 } },
        store: { goal: '', lines: [] },
      }),
    );
    expect(screen.getByRole('button', { name: 'Resume model calls' })).toBeTruthy();
    await open(page);
    expect(screen.getByText(/Exact recorded accounting: 4 calls/)).toBeTruthy();
    expect(screen.getByText(/does not establish whether a process is alive/)).toBeTruthy();
    expect(page.posts(POST)).toBe(0);
    await press(screen.getByRole('button', { name: 'Refresh recovery records' }));
    await page.settle();
    expect(page.gets(GET)).toBe(2);
  });
  it('posts once per press and removes only a confirmed retired record', async () => {
    const page = mountDrift({
      routes: { [GET]: () => json({ ok: true, long_history: LONG_HISTORY }), [POST]: () => 'hold' },
    });
    await open(page);
    await act(async () => {
      discard().click();
      discard().click();
    });
    expect(page.posts(POST)).toBe(1);
    expect(page.state.requests.find((r) => r.path === POST)?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      job: HISTORY_ITEM.job_id,
      press: true,
      observer_model: 1,
    });
    await page.release(POST, json({ ok: true, discarded: true, reason: 'receipt-unresolved' }));
    expect(screen.getByText(/record was removed.*cleanup remains unconfirmed/)).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: 'Check and discard superseded record' }),
    ).toBeNull();
    expect(page.gets(GET)).toBe(1);
  });
  it('retains minimum, unknown and active records without discard authority', async () => {
    const items = [
      { ...HISTORY_ITEM, state: 'active', terminal_at: null },
      { ...HISTORY_ITEM, job_id: 'b'.repeat(32), accounting: 'minimum', exact: null },
      {
        ...HISTORY_ITEM,
        job_id: 'c'.repeat(32),
        accounting: 'unknown',
        exact: null,
        minimum: null,
        unsettled: null,
      },
    ];
    const page = mountDrift({
      routes: {
        [GET]: () =>
          json({
            ok: true,
            long_history: {
              ...LONG_HISTORY,
              items,
              incomplete: true,
              reason: 'accounting-unavailable',
            },
          }),
      },
    });
    await open(page);
    expect(screen.getByText(/Minimum recorded accounting: at least 4 calls/)).toBeTruthy();
    expect(screen.getByText(/Recorded accounting: unknown/)).toBeTruthy();
    expect(
      screen.queryByRole('button', { name: 'Check and discard superseded record' }),
    ).toBeNull();
    expect(page.posts(POST)).toBe(0);
  });
  it.each(['refused', 'lost', 'malformed'])(
    'keeps uncertainty after %s answer without automatic retries',
    async (answer) => {
      const page = mountDrift({
        routes: {
          [GET]: () => json({ ok: true, long_history: LONG_HISTORY }),
          [POST]: () => {
            if (answer === 'lost') throw new Error('private transport');
            return new Response(
              JSON.stringify(
                answer === 'refused'
                  ? { ok: false, discarded: false, reason: 'owner-current' }
                  : { ok: true },
              ),
              { status: answer === 'refused' ? 409 : 200 },
            );
          },
        },
      });
      await open(page);
      await press(discard());
      await page.settle();
      expect(screen.getByText(/did not confirm.*discard|Could not confirm whether/)).toBeTruthy();
      expect(discard()).toBeTruthy();
      await page.poll(driftBoard());
      await page.settle();
      expect(page.posts(POST)).toBe(1);
      expect(page.gets(GET)).toBe(1);
      expect(document.body.textContent).not.toContain('private transport');
    },
  );
  it('aborts navigation and ignores late discard answers, with no read on return', async () => {
    const page = mountDrift({
      routes: { [GET]: () => json({ ok: true, long_history: LONG_HISTORY }), [POST]: () => 'hold' },
    });
    await open(page);
    await press(discard());
    await page.go('#n=sessions');
    await page.release(POST, json({ ok: true, discarded: true, reason: '' }));
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(page.gets(GET)).toBe(1);
    expect(page.posts(POST)).toBe(1);
    expect(screen.queryByText(/record was removed/)).toBeNull();
  });

  it('never reads history as a side effect of Resume model calls', async () => {
    const page = mountDrift({
      payload: { reading: { ...POLICY, off: true } },
      routes: { '/api/reading': () => json({ ok: true, off: false }) },
    });
    await page.settle();
    await press(screen.getByRole('button', { name: 'Resume model calls' }));
    await page.settle();
    expect(page.gets(GET)).toBe(0);
    expect(page.posts(POST)).toBe(0);
  });
  it('does not fetch on disclosure restoration and ignores an old session GET', async () => {
    const page = mountDrift({ routes: { [GET]: () => 'hold' } });
    await open(page);
    await page.go('#n=sessions');
    await page.release(GET, json({ ok: true, long_history: LONG_HISTORY }));
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(page.gets(GET)).toBe(1);
    expect(screen.queryByText(/Exact recorded accounting/)).toBeNull();
    expect(screen.getByText('Recovery records have not been read in this view.')).toBeTruthy();
    expect(page.posts(POST)).toBe(0);
  });
  it('retains the previous inspection when explicit Refresh fails without displaying raw data', async () => {
    const page = mountDrift({
      routes: { [GET]: () => json({ ok: true, long_history: LONG_HISTORY }) },
    });
    await open(page);
    page.state.routes[GET] = () =>
      json({ ok: true, long_history: { ...LONG_HISTORY, reason: '/private/path' } });
    await press(screen.getByRole('button', { name: 'Refresh recovery records' }));
    await page.settle();
    expect(screen.getByText(/Any earlier inspection remains below/)).toBeTruthy();
    expect(screen.getByText(/Exact recorded accounting: 4 calls/)).toBeTruthy();
    expect(document.body.textContent).not.toContain('/private/path');
    expect(page.gets(GET)).toBe(2);
    expect(page.posts(POST)).toBe(0);
  });
  it.each(['sample', 'view-only'])('offers no history action in %s', async (mode) => {
    const page = mountDrift(
      mode === 'sample' ? { hash: SAMPLE_FRAGMENT } : { payload: { annotate: false } },
    );
    await page.settle();
    expect(screen.queryByRole('button', { name: 'Unfinished long analysis records' })).toBeNull();
    expect(page.gets(GET)).toBe(0);
    expect(page.posts(POST)).toBe(0);
  });
});
