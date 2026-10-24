import { describe, expect, it } from 'vitest';
import { byAction, fact, json, mountDrift, press, readingPosts } from './testing';

/* Analyze drift stays beside a later direction's choices, and settling and analyzing are two presses. */
const LATER = fact('d1', 995, { summary: 'Do it the careful way' });
const routes = {
  '/api/direction': () => json({ ok: true, text: 'Do it the careful way', clipped: false }),
  '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true, revision: 4 }),
  '/api/reading': () => json({ ok: true, job: { id: 'j9', steps: [] } }),
};
const session = { annotation_goal_saved_at: 500, annotation_at: 500 };

describe('Analyze drift beside a later direction', () => {
  it('is offered with the three choices and starts one reading on its first press, settling nothing', async () => {
    const page = mountDrift({
      facts: [LATER],
      session,
      routes: { ...routes, '/api/reading': () => 'hold' },
    });
    await page.settle();
    await page.settle();
    expect(byAction('reading-ask')?.textContent).toBe('Analyze drift');
    expect(byAction('direction-keep')?.textContent).toBe('Leave it');
    await press(byAction('reading-ask'));
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({ provider: 'claude', press: true });
    expect(readingPosts(page)[0]?.body).not.toHaveProperty('settle_through');
    expect(readingPosts(page)[0]?.body).not.toHaveProperty('allow');
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/annotate'),
    ).toEqual([]);
  });

  it('is not a way to settle: Leave it settles on its own first press and starts no reading', async () => {
    const page = mountDrift({ facts: [LATER], session, routes });
    await page.settle();
    await page.settle();
    await press(byAction('direction-keep'));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/annotate'),
    ).toHaveLength(1);
  });
});

describe('the refusal under the question', () => {
  it("says what kind of absence it is, as the Analyze control's refusal does", async () => {
    const page = mountDrift({
      facts: [LATER],
      session,
      routes,
      payload: { reading: { reason: 'run-disabled', used: 0, limit: 10 } },
    });
    await page.settle();
    await page.settle();
    const refused = document.querySelector('#next-cockpit-reading-refused') as HTMLElement;
    expect(refused.textContent).toContain('Model calls are off for this run');
    expect(refused.getAttribute('data-absence')).toBe('run-config');
  });
});
