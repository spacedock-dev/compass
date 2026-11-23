import { act, fireEvent, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { mountShell } from '../shell/testing';

const waiting = {
  harness: 'claude',
  project: 'api',
  sid: 'gate',
  title: 'Check deployment',
  state: 'needs_input',
  state_detail: 'Waiting for approval',
};
const flagged = {
  ...waiting,
  sid: 'dirty',
  title: 'Finish the migration',
  state: 'idle',
  ended_at: 900,
  dirty: true,
  changed: 2,
};
const clean = { ...flagged, sid: 'clean', title: 'Update the guide', dirty: false };
const board = { generated: 1000, dismiss: true, sessions: [flagged, clean, waiting] };

it('draws the Waiting on you queue first and counts a gate with a question once', async () => {
  const page = mountShell({
    hash: '#n=attention',
    data: {
      ...board,
      ask: true,
      asks: [{ id: 'ask', harness: 'claude', session_id: 'gate', question: 'Deploy?' }],
    },
  });
  expect(screen.getByRole('link', { name: 'Needs you' })).toBeVisible();
  await page.settle();
  expect(screen.getAllByRole('heading', { level: 2 })[0]?.textContent).toBe('Waiting on you (1)');
  expect(screen.getByRole('link', { name: 'Needs you 2' })).toBeVisible();
  expect(screen.getByText('Deploy?')).toBeVisible();
  expect(screen.getByText('Waiting for approval')).toBeVisible();
});

it('dismisses, undoes and marks read through the server and waits for the board to remove rows', async () => {
  const page = mountShell({ hash: '#n=attention', data: board });
  const post = vi.spyOn(page.shell.runtime.client, 'postDismiss').mockResolvedValue({
    kind: 'ok',
    body: { ok: true, persisted: true },
    status: 200,
    revision: '',
  });
  await page.settle();

  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  expect(post).toHaveBeenNthCalledWith(1, { harness: 'claude', sid: 'dirty' });
  expect(screen.getByText('Finish the migration')).toBeVisible();
  fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
  expect(post).toHaveBeenNthCalledWith(2, { harness: 'claude', sid: 'dirty', clear: false });

  expect((await screen.findAllByText('Restored.'))[0]).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }));
  expect(post).toHaveBeenNthCalledWith(3, { harness: 'claude', sid: 'clean' });
  expect(screen.getByText('Update the guide')).toBeVisible();
  expect((await screen.findAllByText('Marked as read.'))[0]).toBeVisible();

  page.backend.data = { ...board, sessions: [waiting] };
  await act(async () => void (await page.shell.runtime.refresh()));
  expect(screen.queryByText('Finish the migration')).toBeNull();
  expect(screen.queryByText('Update the guide')).toBeNull();
  expect(post).toHaveBeenCalledTimes(3);
});

it('posts actions for two different sessions even while the first write is outstanding', async () => {
  const page = mountShell({ hash: '#n=attention', data: board });
  await page.settle();
  const post = vi.spyOn(page.shell.runtime.client, 'postDismiss');
  post.mockImplementationOnce(() => new Promise(() => undefined));
  post.mockResolvedValueOnce({
    kind: 'ok',
    body: { ok: true, persisted: true },
    status: 200,
    revision: '',
  });

  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  fireEvent.click(screen.getByRole('button', { name: 'Mark as read' }));
  expect(post).toHaveBeenNthCalledWith(2, { harness: 'claude', sid: 'clean' });
});

it('keeps one waiting row and shows its measured dirty end', async () => {
  const page = mountShell({
    hash: '#n=attention',
    data: {
      ...board,
      sessions: [flagged],
      ask: true,
      asks: [
        { id: 'ask', harness: 'claude', session_id: flagged.sid, question: 'Review the report?' },
      ],
    },
  });
  await page.settle();
  expect(screen.getByRole('heading', { name: 'Waiting on you (1)' })).toBeVisible();
  expect(screen.getByText('Review the report?')).toBeVisible();
  expect(screen.getByText('Session ended with uncommitted work: 2 changed entries')).toBeVisible();
  expect(screen.getByRole('link', { name: 'Needs you 1' })).toBeVisible();
});
