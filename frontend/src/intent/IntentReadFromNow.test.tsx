import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { clock } from '../observed';
import { board, control, goalBox, inert, mountSession, stored, text, type } from './panel.testing';

/* The owner's ruling of 2026-10-21 (docs/design-reading-a-session.md, "Amended 2026-10-21 (owner): editing the
   goal keeps the reading's start"): Save intent keeps the reading's original start, and Read from my latest message is the
   reader's explicit choice to move it, said in the moment with the time it moved to. */

const OPENED = 1_000;
const MOVED = 1_900;

const footerCue = () => text('.next-cockpit-held-footer .next-cockpit-held-cue');

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};

function saved(window: number) {
  return { annotation_window_start: window, annotation_at: 990 };
}

describe('a goal edit over saved words', () => {
  it('sends no request to move the start, so the server keeps the one the reading had', async () => {
    const page = mountSession({
      store: { goal: 'Ship the queue worker', revision: 1 },
      session: saved(OPENED),
      routes: { '/api/annotate': () => stored(2) },
    });
    await settle(page);
    type(goalBox(), 'Ship the queue worker and record the ruling');
    await act(async () => {
      fireEvent.click(control('held-save') as Element);
    });
    await settle(page);
    const posts = page.allPosts();
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: 'Ship the queue worker and record the ruling',
      expected_revision: 1,
    });
    expect(footerCue()).toBe('Saved.');
  });
});

describe('Read from my latest message', () => {
  it('is not offered before anything is saved, where the first save opens the window by itself', async () => {
    const page = mountSession();
    await settle(page);
    expect(control('held-save-from-now')).toBeNull();
  });

  it('is offered beside Save intent over saved words, inert until there is something to save', async () => {
    const page = mountSession({
      store: { goal: 'Ship the queue worker', revision: 1 },
      session: saved(OPENED),
    });
    await settle(page);
    expect(control('held-save-from-now')?.textContent).toBe('Read from my latest message');
    expect(inert(control('held-save-from-now'))).toBe(true);
    type(goalBox(), 'Ship the queue worker and record the ruling');
    expect(inert(control('held-save-from-now'))).toBe(false);
  });

  it('saves, asks the server to move the start, and says so with the time it moved to', async () => {
    const page = mountSession({
      store: { goal: 'Ship the queue worker', revision: 1 },
      session: saved(OPENED),
      routes: {
        '/api/annotate': () => {
          page.state.data = board(saved(MOVED), {
            goal: 'Ship the queue worker and record the ruling',
            revision: 2,
          });
          return stored(2);
        },
      },
    });
    await settle(page);
    type(goalBox(), 'Ship the queue worker and record the ruling');
    await act(async () => {
      fireEvent.click(control('held-save-from-now') as Element);
    });
    await settle(page);
    const posts = page.allPosts();
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: 'Ship the queue worker and record the ruling',
      expected_revision: 1,
      read_from_now: true,
    });
    const said = `Saved. Compass now reads from ${clock(MOVED)}. Work before that is not read.`;
    expect(footerCue()).toBe(said);
    // And once, in the polite region, after the paint that shows it.
    expect(text('#next-cockpit-cue-status')).toBe(said);
    expect(text('.next-cockpit-held-stamp')).toContain(`reads from ${clock(MOVED)}`);
  });
});
