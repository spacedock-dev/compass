import { act } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { liveRow } from './context';
import { editGoal, board, goalBox, mountSession, type } from './panel.testing';

/* A reader who moves from one session to another meets the other session's own editors, never the first
   one's words. */

describe('moving to another session', () => {
  it('builds new editors, so the native undo stack of the first session cannot reach the second', async () => {
    // Equal saved goals are the case the node is kept for: the editors only replace a node whose text differs.
    const first = board({ annotation_goal: 'Same goal', annotation_revision: 1 });
    const data = {
      ...first,
      sessions: [
        ...first.sessions,
        { ...first.sessions[0], sid: 's2', title: 'Beta work', annotation_goal: 'Same goal' },
      ],
    };
    const page = mountSession({
      strict: false,
      session: { annotation_goal: 'Same goal', annotation_revision: 1 },
    });
    page.state.data = data;
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    await page.settle();
    editGoal();
    const before = goalBox();
    // Type and take it back: the box reads the saved goal again, but its native undo stack now holds the typing.
    type(before, 'Same goalX');
    type(before, 'Same goal');
    act(() => {
      page.router.navigate({
        view: 'session',
        project: 'alpha/app',
        harness: 'claude',
        session: 's2',
      });
    });
    await page.settle();
    editGoal();
    const after = goalBox();
    expect(after).not.toBe(before);
    expect(after.value).toBe('Same goal');
    expect(page.posts()).toBe(0);
  });
});

describe('the live row of a session', () => {
  it('is matched on the harness as well as the sid', () => {
    const rows = [
      { harness: 'claude', sid: 'shared', title: 'Claude row' },
      { harness: 'codex', sid: 'shared', title: 'Codex row' },
    ];
    const ctx = {
      shell: { runtime: { store: { getSnapshot: () => ({ data: { sessions: rows } }) } } },
    } as unknown as Parameters<typeof liveRow>[0];
    expect(liveRow(ctx, { harness: 'codex', sid: 'shared' })?.['title']).toBe('Codex row');
    expect(liveRow(ctx, { harness: 'claude', sid: 'shared' })?.['title']).toBe('Claude row');
    expect(liveRow(ctx, { harness: 'cursor', sid: 'shared' })).toBeNull();
  });
});
