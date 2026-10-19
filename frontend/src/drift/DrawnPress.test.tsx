import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ROUTE,
  byAction,
  check,
  driftBoard,
  json,
  mountDrift,
  press,
  readingPosts,
  textOf,
} from './testing';

/* A press acts on what the reader was shown. The card can be held while a board arrives (a focused correction
   box), and then the board the handler reads is newer than the card the reader read; what a press sends is the
   card's, and where the two differ nothing is sent and the reader is told. */
const ASSESSMENT = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  criteria: {
    goal: { result: 'departure', cites: ['c1'], detail: 'It stopped.', clause: 'Ship the queue' },
  },
};
const session = { annotation_assessment: ASSESSMENT, annotation_window_start: 100 };
const FACTS = [
  check('c1', 500, 'failed', { result_source: 'failed flag' }),
  check('c2', 1100, 'passed'),
];
const PARTS = ['Your last check failed', { entry: 'c1' }, '. Fix it.'];
const routes = {
  '/api/correction': () => json({ ok: true, parts: PARTS }),
  '/api/reading': () => json({ ok: true, produced: false }),
  '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true }),
};
const later = (extra: Record<string, unknown>, sessionExtra: Record<string, unknown> = {}) => ({
  ...driftBoard({ session: { ...session, ...sessionExtra }, payload: extra }),
  generated: 1300,
});

/* The reader opens Steer back, which takes focus, so the card is held from here on. */
async function hold(page: ReturnType<typeof mountDrift>) {
  await press(byAction('steer-back'));
  await page.settle();
  const box = document.querySelector<HTMLTextAreaElement>('#next-cockpit-correction');
  expect(box).not.toBeNull();
  box?.focus();
}

describe('Turn on sends what the card showed', () => {
  const off = { reading: { consent: false, off: true, reason: 'readings-off' } };
  const open = async (route: Record<string, unknown> = ROUTE) => {
    const page = mountDrift({
      session,
      facts: FACTS,
      payload: { ...off, reading_routes: { claude: route } },
      routes,
    });
    await page.settle();
    await page.settle();
    await hold(page);
    return page;
  };
  const moved = (patch: Record<string, unknown>) =>
    later({ ...off, reading_routes: { claude: { ...ROUTE, ...patch } } });

  it.each([
    [
      'where the words go',
      { words_destination: 'evil.example' },
      /Where this session would be sent changed/,
    ],
    [
      'where tool output goes',
      { destination: 'evil.example' },
      /Where this session would be sent changed/,
    ],
    ['who reads it', { provider: 'codex' }, /The reader for this session changed/],
    ['the model', { model: 'other' }, /The reader for this session changed/],
  ])(
    'refuses, sending nothing, when %s moved while the card was held',
    async (_name, patch, said) => {
      const page = await open();
      await page.poll(moved(patch));
      await press(byAction('reading-on'));
      await page.settle();
      expect(readingPosts(page)).toEqual([]);
      expect(textOf('.next-session-drift')).toMatch(said);
      // And the press that follows is the reader's own, over the card the reader now sees.
      await page.advance(5_000);
      expect(readingPosts(page)).toEqual([]);
    },
  );

  it('sends the drawn values when nothing moved', async () => {
    const page = await open();
    await press(byAction('reading-on'));
    await page.settle();
    expect(readingPosts(page)).toHaveLength(1);
    expect(readingPosts(page)[0]?.body).toMatchObject({
      provider: 'claude',
      model: 'm',
      allow: true,
      words_destination: 'api',
      tool_output: 'api',
    });
  });
});

describe('the revision a press names is the one the card was drawn against', () => {
  it('refuses with the revision sentence, sending nothing, when the words moved on under a held card', async () => {
    const page = mountDrift({ session, facts: FACTS, routes });
    await page.settle();
    await page.settle();
    await hold(page);
    await page.poll(later({}, { annotation_revision: 4, annotation_revision_count: 4 }));
    await press(byAction('reading-ask'));
    await page.settle();
    expect(readingPosts(page)).toEqual([]);
    expect(textOf('.next-session-drift')).toContain(
      'your intent changed since this page was drawn',
    );
  });
});

describe('Not accurate acts on the state the card showed', () => {
  it('marks, rather than un-marks, when another tab marked it while the card was held', async () => {
    const page = mountDrift({ session, facts: FACTS, routes });
    await page.settle();
    await page.settle();
    expect(byAction('not-accurate')?.textContent).toBe('Mark as inaccurate');
    await hold(page);
    await page.poll(later({}, { annotation_not_accurate: true }));
    await act(async () => {
      fireEvent.click(byAction('not-accurate') as Element);
    });
    await page.settle();
    const posts = page.state.requests.filter(
      (r) => r.method === 'POST' && r.path === '/api/annotate',
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toMatchObject({ not_accurate: true, read_at: 1000 });
  });
});
