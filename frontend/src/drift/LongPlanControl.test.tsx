import { act, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SAMPLE_FRAGMENT } from '../sample/ids';
import { LONG_PLAN } from '../../test/longPlan';
import { json, mountDrift, press, readingPosts, ROUTE, driftBoard } from './testing';

const gets = (page: ReturnType<typeof mountDrift>) =>
  page.state.requests.filter((r) => r.path === '/api/reading-long-plan');
async function opened(over: Record<string, unknown> = {}, reply = { ok: true, produced: false }) {
  const page = mountDrift({
    payload: { reading_routes: { claude: { ...ROUTE, ci_read: 'on' } } },
    routes: {
      '/api/reading-long-plan': () => json({ ok: true, long_plan: { ...LONG_PLAN, ...over } }),
      '/api/reading': () => json(reply),
    },
  });
  await page.settle();
  expect(gets(page)).toHaveLength(0);
  await press(screen.getByRole('button', { name: 'Long analysis options' }));
  await page.settle();
  return page;
}

describe('explicit long preview and Start', () => {
  it('expands once with GET only and renders server limits and unknown estimates honestly', async () => {
    const page = await opened({
      source: { ...LONG_PLAN.source, parent_bytes: null, observed_at: null },
    });
    expect(gets(page)).toHaveLength(1);
    expect(readingPosts(page)).toEqual([]);
    expect(screen.getByText(/Parent file extent: Unknown/)).toBeTruthy();
    expect(screen.getByText(/retained object graph.*not.*RSS/i)).toBeTruthy();
    expect(screen.getByText(/16 evidence.*1 reconciliation.*17/)).toBeTruthy();
    expect(screen.getByText(/not reserved.*not a guarantee/)).toBeTruthy();
  });
  it('posts the drawn binding exactly once through existing reading safeguards', async () => {
    const page = await opened();
    const start = screen.getByRole('button', { name: 'Start long analysis' });
    await act(async () => {
      start.click();
      start.click();
    });
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({
      mode: 'long',
      plan_binding: LONG_PLAN.binding,
      harness: 'claude',
      sid: 's1',
      provider: 'claude',
      model: 'm',
      destination: 'api',
      words_destination: 'api',
      expected_revision: 3,
      press: true,
      observer_model: 1,
    });
    expect(screen.getByRole('button', { name: 'Refresh long preview' })).toBeTruthy();
    expect(gets(page)).toHaveLength(1);
  });
  it('shows stale refusal and never refreshes or retries automatically', async () => {
    const page = mountDrift({
      payload: { reading_routes: { claude: { ...ROUTE, ci_read: 'on' } } },
      routes: {
        '/api/reading-long-plan': () => json({ ok: true, long_plan: LONG_PLAN }),
        '/api/reading': () =>
          new Response(JSON.stringify({ ok: false, reason: 'plan-changed' }), { status: 409 }),
      },
    });
    await page.settle();
    await press(screen.getByRole('button', { name: 'Long analysis options' }));
    await page.settle();
    await press(screen.getByRole('button', { name: 'Start long analysis' }));
    await page.settle();
    expect(screen.getAllByText(/Refresh the long preview/).length).toBeGreaterThan(0);
    expect(readingPosts(page)).toHaveLength(1);
    expect(gets(page)).toHaveLength(1);
  });
  it('offers no Start for unsupported or malformed capability', async () => {
    const page = await opened({
      supported: false,
      can_start: false,
      reason: 'unsupported-source',
      source: {
        ...LONG_PLAN.source,
        capability: 'unsupported',
        kinds: [],
        parent_bytes: null,
        observed_at: null,
      },
    });
    expect(screen.queryByRole('button', { name: 'Start long analysis' })).toBeNull();
    expect(readingPosts(page)).toEqual([]);
  });
  it('requires current saved intent and refuses changed descriptor destinations without a POST', async () => {
    const page = await opened({ route: { ...LONG_PLAN.route, destination: 'another endpoint' } });
    await press(screen.getByRole('button', { name: 'Start long analysis' }));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
  });
  it('requires explicit refresh after saved intent changes and never replaces the drawn binding on poll', async () => {
    const page = await opened();
    await page.poll(
      driftBoard({
        store: { revision: 4 },
        payload: { reading_routes: { claude: { ...ROUTE, ci_read: 'on' } } },
      }),
    );
    await press(screen.getByRole('button', { name: 'Start long analysis' }));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
    expect(gets(page)).toHaveLength(1);
    page.state.routes['/api/reading-long-plan'] = () =>
      json({
        ok: true,
        long_plan: {
          ...LONG_PLAN,
          binding: 'b'.repeat(64),
          intent: { ...LONG_PLAN.intent, revision: 4 },
        },
      });
    await press(screen.getByRole('button', { name: 'Refresh long preview' }));
    await page.settle();
    await press(screen.getByRole('button', { name: 'Start long analysis' }));
    await page.settle();
    expect(readingPosts(page)[0]?.body).toMatchObject({
      plan_binding: 'b'.repeat(64),
      expected_revision: 4,
    });
    expect(gets(page)).toHaveLength(2);
  });
  it('ignores a late preview after navigation and never transfers it to the next session', async () => {
    const page = mountDrift({ routes: { '/api/reading-long-plan': () => 'hold' } });
    await page.settle();
    await press(screen.getByRole('button', { name: 'Long analysis options' }));
    await act(async () => {
      page.router.navigate({ view: 'sessions' });
    });
    await page.settle();
    await page.release('/api/reading-long-plan', json({ ok: true, long_plan: LONG_PLAN }));
    expect(screen.queryByRole('button', { name: 'Start long analysis' })).toBeNull();
    expect(readingPosts(page)).toEqual([]);
    expect(gets(page)).toHaveLength(1);
  });
  it('does not offer or fetch long options in view-only mode', async () => {
    const page = mountDrift({ payload: { annotate: false } });
    await page.settle();
    expect(screen.queryByRole('button', { name: 'Long analysis options' })).toBeNull();
    expect(gets(page)).toEqual([]);
    expect(readingPosts(page)).toEqual([]);
  });
  it('rejects malformed descriptors without offering Start', async () => {
    const page = await opened({ extra: 'unsafe extension' });
    expect(screen.queryByRole('button', { name: 'Start long analysis' })).toBeNull();
    expect(screen.getByText(/preview is unavailable or could not be read/)).toBeTruthy();
    expect(readingPosts(page)).toEqual([]);
  });

  it('does not offer or fetch long options in the sample', async () => {
    const page = mountDrift({ hash: SAMPLE_FRAGMENT });
    await page.settle();
    expect(screen.queryByRole('button', { name: 'Long analysis options' })).toBeNull();
    expect(gets(page)).toEqual([]);
    expect(readingPosts(page)).toEqual([]);
  });
  it('saves a found goal through the shared owner but requires a fresh preview before any long POST', async () => {
    const page = mountDrift({
      store: { goal: '', lines: ['Tests pass'], revision: 3 },
      payload: { reading_routes: { claude: { ...ROUTE, ci_read: 'on' } } },
      routes: {
        '/api/reading-long-plan': () => json({ ok: true, long_plan: LONG_PLAN }),
        '/api/annotate': () =>
          json({ ok: true, outcome: 'stored', persisted: true, revision: 4, saved_revision: 4 }),
        '/api/goal/find': () =>
          json({
            ok: true,
            produced: true,
            why: '',
            found: {
              goal: 'Ship the queue',
              found_at: 1000,
              cites: [{ fact_id: 'u1', ordinal: 1, at: 100, quotes: ['Ship the queue'] }],
            },
            route: {
              label: 'Claude Code',
              provider: 'claude',
              model: 'm',
              harness: 'claude',
              vendor: 'A',
            },
          }),
      },
    });
    await page.settle();
    await press(screen.getByRole('button', { name: 'Find goal' }));
    await page.settle();
    await press(screen.getByRole('button', { name: 'Long analysis options' }));
    await page.settle();
    await press(screen.getByRole('button', { name: 'Start long analysis' }));
    await page.settle();
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/annotate'),
    ).toHaveLength(1);
    expect(readingPosts(page)).toEqual([]);
    expect(gets(page)).toHaveLength(1);
    expect(
      screen.getAllByText(/Your goal was saved. Refresh the long preview/).length,
    ).toBeGreaterThan(0);
  });
});
