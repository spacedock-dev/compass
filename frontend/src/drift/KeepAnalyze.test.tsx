import { describe, expect, it } from 'vitest';
import { byAction, fact, json, mountDrift, press, readingPosts, textOf } from './testing';

/* Keep settles and reads together when the reading policy permits it. */
const LATER = fact('d1', 995, { summary: 'Do it the careful way' });
const routes = {
  '/api/direction': () => json({ ok: true, text: 'Do it the careful way', clipped: false }),
  '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true, revision: 4 }),
  '/api/reading': () => json({ ok: true, settled: 'stored', job: { id: 'j9', steps: [] } }),
};
const session = { annotation_goal_saved_at: 500, annotation_at: 500 };

describe('Keep my intent and analyze', () => {
  it('tells a reader beside Keep and analyze when the source cannot be reached and sends no reading', async () => {
    const page = mountDrift({
      facts: [LATER],
      session,
      routes: { ...routes, '/api/direction': () => json({ ok: false, reason: 'out_of_reach' }) },
    });
    await page.settle();
    await page.settle();
    const button = byAction('direction-keep') as HTMLButtonElement;
    expect(button.textContent).toBe('Keep my intent and analyze');
    button.focus();
    await press(button);
    await page.settle();
    expect(button.parentElement?.querySelector('[data-next-action-feedback]')?.textContent).toBe(
      'That direction is beyond the part of the record Compass could search. Nothing was settled and no analysis was started.',
    );
    expect(document.activeElement).toBe(button);
    expect(readingPosts(page)).toHaveLength(0);
  });

  it('announces the settlement refusal at Keep and analyze after the reader has seen the whole direction', async () => {
    const page = mountDrift({
      facts: [LATER],
      session,
      routes: { ...routes, '/api/reading': () => json({ ok: false, adoption_refused: true }, 422) },
    });
    await page.settle();
    await page.settle();
    await press(byAction('direction-keep'));
    await page.settle();
    const button = byAction('direction-keep') as HTMLButtonElement;
    button.focus();
    await press(button);
    await page.settle();
    const message = button.parentElement?.querySelector('[data-next-action-feedback]')?.textContent;
    expect(message).toMatch(/Nothing was settled.*Review your intent and press again\.$/);
    expect(document.querySelector('#next-cockpit-cue-status')?.textContent).toBe(message);
    expect(document.activeElement).toBe(button);
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).not.toHaveProperty('allow');
  });
  it('lets a reader review several directions from one batch before Keep and analyze sends a reading', async () => {
    const page = mountDrift({
      facts: [LATER, fact('d2', 996, { summary: 'Second direction' })],
      session,
      routes: {
        ...routes,
        '/api/direction': () =>
          json({
            results: [
              { ok: true, text: 'Do it the careful way', clipped: false },
              { ok: true, text: 'Second complete direction', clipped: false },
            ],
          }),
      },
    });
    await page.settle();
    await page.settle();
    await press(byAction('direction-keep'));
    await page.settle();
    const reads = page.state.requests.filter(
      (r) => r.method === 'POST' && r.path === '/api/direction',
    );
    expect(reads).toHaveLength(1);
    expect(reads[0]?.body).toMatchObject({ fact_ids: ['d1', 'd2'] });
    expect(textOf('[data-next-cockpit-direction-whole]')).toContain('Second complete direction');
    expect(readingPosts(page)).toHaveLength(0);
    await press(byAction('direction-keep'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({ settle_through: 996 });
  });

  it('settles and starts the analysis in one reading request, once', async () => {
    const page = mountDrift({
      facts: [LATER],
      session,
      routes: { ...routes, '/api/reading': () => 'hold' },
    });
    await page.settle();
    await page.settle();
    const keep = byAction('direction-keep') as HTMLElement;
    expect(keep.textContent).toBe('Keep my intent and analyze');
    expect(keep.getAttribute('data-variant') === 'primary').toBe(true);
    await press(keep);
    await press(byAction('direction-keep'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({
      provider: 'claude',
      press: true,
      observer_model: 1,
      settle_through: 995,
      expected_revision: 3,
    });
    expect(readingPosts(page)[0]?.body).not.toHaveProperty('allow');
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/annotate'),
    ).toEqual([]);
  });

  it('settles and analyzes directly with no legacy provider grant', async () => {
    const page = mountDrift({
      facts: [LATER],
      session,
      routes,
      payload: {
        reading: {
          consent: true,
          off: false,
          providers: {},
          words: {},
          tool_output: {},
          used: 0,
          limit: 10,
        },
      },
    });
    await page.settle();
    await page.settle();
    expect(byAction('direction-keep')?.textContent).toBe('Keep my intent and analyze');
    await press(byAction('direction-keep'));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
    expect(textOf('[data-next-cockpit-direction-whole]')).toContain('Do it the careful way');
    await press(byAction('direction-keep'));
    await page.settle();
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/annotate'),
    ).toHaveLength(0);
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).not.toHaveProperty('allow');
  });
});

describe('Keep during a held close', () => {
  it('settles and reads nothing where the board already says no reading can start, and learns that', async () => {
    const quiet = { ok: false, reason: 'idle-unknown', sentence: 'Not recorded.' };
    const page = mountDrift({ facts: [LATER], session, routes });
    await page.settle();
    await page.settle();
    expect(byAction('direction-keep')?.textContent).toBe('Keep my intent and analyze');
    await page.poll({
      ...(page.state.data as { sessions: object[] }),
      generated: 1100,
      sessions: [
        { ...(page.state.data as { sessions: object[] }).sessions[0], reading_eligibility: quiet },
      ],
    });
    // The close is held: the card still offers the analysis.
    expect(byAction('direction-keep')?.textContent).toBe('Keep my intent and analyze');
    await press(byAction('direction-keep'));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
    expect(textOf('[data-next-cockpit-direction-whole]')).toContain('Do it the careful way');
    await press(byAction('direction-keep'));
    await page.settle();
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/annotate'),
    ).toHaveLength(1);
    expect(byAction('direction-keep')?.textContent).toBe('Keep my intent');
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
