import { toHaveTextContent, toHaveAttribute } from '@testing-library/jest-dom/matchers';
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { locationBoard, locationRow, locationRows } from '../../test/location_boards';
import { mountShell } from '../shell/testing';
import { mountProject } from '../project/testing';
import { observe } from '../observed';
import { buildSessionsScreen } from '../sessions/rows';
import { EMPTY_FILTERS, indexScreen, prepare, projectOptions } from '../sessions/filters';

expect.extend({ toHaveTextContent, toHaveAttribute });

describe('a label is interpreted by measured locations', () => {
  it.each(['directory', 'worktrees'])(
    'a person sees nine %s sessions without a location warning',
    async (layout) => {
      const data = locationBoard();
      if (layout === 'worktrees')
        for (const [i, row] of locationRows(data).entries()) {
          row['project_key'] = 'git:audits';
          row['project_identity_source'] = 'git common directory';
          row['worktree'] = `target-${String(i)}`;
        }
      const page = mountShell({ hash: '#n=attention', data });
      await page.settle();
      expect(document.body).not.toHaveTextContent('Identity collision');
      expect(document.querySelector('[data-next-board-risk="collision"]')).toBeNull();
      page.unmount();
      const sessions = mountShell({ hash: '#n=sessions', data });
      await sessions.settle();
      expect(document.querySelectorAll('.next-operation-collision')).toHaveLength(0);
      expect(document.querySelectorAll('.next-operation-route')).toHaveLength(9);
      if (layout === 'worktrees') expect(document.body).toHaveTextContent('target-8');
      sessions.unmount();
      const project = mountProject({ hash: '#n=project:audits', data });
      await project.settle();
      expect(document.querySelector('.next-project-detail-collision')).toBeNull();
      project.unmount();
    },
  );

  it('a person can open every member of a label spanning two measured locations', async () => {
    const data = locationBoard(2);
    locationRow(data, 1)['project_key'] = 'path:other';
    const page = mountShell({ hash: '#n=attention', data });
    await page.settle();
    const card = document.querySelector('[data-next-board-risk="collision"]') as HTMLElement;
    expect(card).toHaveTextContent('2 measured locations');
    expect(card).toHaveTextContent('title, worktree, id and start time');
    expect(card).not.toHaveTextContent('path:other');
    for (const row of locationRows(data)) {
      expect(
        within(card).getByRole('link', { name: new RegExp(String(row['title'])) }),
      ).toHaveAttribute('href', `#n=session:audits:claude:${String(row['sid'])}`);
    }
    expect(
      within(card).getByRole('link', { name: 'Label shared across locations' }),
    ).toHaveAttribute('href', '#n=project:audits');
  });

  it.each(
    ['collector project label', 'inferred Claude worktree layout'].flatMap((source) =>
      ['path:audits', 'path:other'].map((key) => ({ source, key })),
    ),
  )(
    'a person sees an unmeasured member from $source with key $key without inventing a second location',
    async ({ source, key }) => {
      const data = locationBoard();
      Object.assign(locationRow(data, 8), {
        project_key: key,
        project_identity_source: source,
      });
      const page = mountShell({ hash: '#n=attention', data });
      await page.settle();
      expect(document.body).toHaveTextContent('Location not measured for 1 session');
      expect(document.body).not.toHaveTextContent('2 measured locations');
      const options = projectOptions(
        indexScreen(buildSessionsScreen(data, observe(data))),
        prepare(EMPTY_FILTERS, 1900000000, true),
      );
      expect(options[0]?.note).not.toContain('more than one location');
      expect(options[0]?.note).toContain('Location not measured for 1 session');
    },
  );

  it('a person reads the unmeasured note only on the row whose location was not measured', async () => {
    const data = locationBoard();
    locationRow(data, 8)['project_identity_source'] = 'inferred Claude worktree layout';
    const sessions = mountShell({ hash: '#n=sessions', data });
    await sessions.settle();
    const notes = [...document.querySelectorAll('.next-operation-collision')].map(
      (note) => note.textContent,
    );
    expect(notes).toEqual(['Location not measured for 1 session with this display label']);
    expect(document.querySelectorAll('.next-operation-route')).toHaveLength(9);
    sessions.unmount();
  });

  it('a person reads only measured members in the location count on every surface', async () => {
    const data = locationBoard(3);
    locationRow(data, 1)['project_key'] = 'path:other';
    locationRow(data, 2)['project_identity_source'] = 'inferred Claude worktree layout';
    const expected =
      '2 sessions share this display label across 2 measured locations. Location not measured for 1 session with this display label';
    const attention = mountShell({ hash: '#n=attention', data });
    await attention.settle();
    const card = document.querySelector('[data-next-board-risk="collision"]') as HTMLElement;
    expect(card.querySelector('.next-attention-risk-observation > p')?.textContent).toBe(expected);
    expect(within(card).getAllByRole('link', { name: /Audit \d/ })).toHaveLength(3);
    attention.unmount();
    const sessions = mountShell({ hash: '#n=sessions', data });
    await sessions.settle();
    // A row says the unmeasured count only when it is one of the unmeasured members.
    const notes = [...document.querySelectorAll('.next-operation-collision')].map(
      (note) => note.textContent,
    );
    expect(notes.sort()).toEqual(
      [
        '2 sessions share this display label across 2 measured locations',
        '2 sessions share this display label across 2 measured locations',
        expected,
      ].sort(),
    );
    sessions.unmount();
    const project = mountProject({ hash: '#n=project:audits', data });
    await project.settle();
    expect(document.querySelector('.next-project-detail-collision')?.textContent).toBe(expected);
  });

  it('a person sees unknown locations even when fallback keys differ', async () => {
    const data = locationBoard(2);
    for (const [i, row] of locationRows(data).entries())
      Object.assign(row, {
        project_key: `fallback-${String(i)}`,
        project_identity_source: 'collector project label',
        state: 'working',
      });
    const page = mountShell({ hash: '#n=attention', data });
    await page.settle();
    expect(document.body).toHaveTextContent('Location not measured for 2 sessions');
    expect(document.body).not.toHaveTextContent('2 measured locations');
    expect(document.body).not.toHaveTextContent('Concurrent sessions');
  });

  it('a person sees concurrent work from checkout identity despite different display names', async () => {
    const data = locationBoard(2);
    for (const row of locationRows(data))
      Object.assign(row, {
        project_key: 'git:audits',
        project_identity_source: 'git common directory',
        worktree: row['sid'] === 'audit-0' ? 'target' : 'display-alias',
        checkout_key: 'checkout:shared',
        state: 'working',
      });
    const page = mountShell({ hash: '#n=attention', data });
    await page.settle();
    expect(
      screen.getByRole('link', { name: 'Concurrent sessions in one checkout' }),
    ).toBeInTheDocument();
  });

  it.each(['different', 'missing', 'empty', 'inferred', 'idle', 'ended'])(
    'a person sees no concurrent claim for %s checkout evidence',
    async (evidence) => {
      const data = locationBoard(2);
      for (const row of locationRows(data))
        Object.assign(row, {
          project_key: 'git:audits',
          project_identity_source: 'git common directory',
          checkout_key: 'checkout:first',
          worktree: 'audit',
          state: 'working',
        });
      const peer = locationRow(data, 1);
      if (evidence === 'different') peer['checkout_key'] = 'checkout:second';
      if (evidence === 'missing') delete peer['checkout_key'];
      if (evidence === 'empty') peer['checkout_key'] = '  ';
      if (evidence === 'inferred')
        peer['project_identity_source'] = 'inferred Claude worktree layout';
      if (evidence === 'idle') peer['state'] = 'idle';
      if (evidence === 'ended') peer['ended_at'] = 1899999999;
      const page = mountShell({ hash: '#n=attention', data });
      await page.settle();
      expect(document.body).not.toHaveTextContent('Concurrent sessions');
    },
  );

  it('a person is warned about simultaneous work in one measured checkout', async () => {
    const data = locationBoard(2);
    locationRow(data, 0)['state'] = 'working';
    locationRow(data, 1)['state'] = 'needs_input';
    const page = mountShell({ hash: '#n=attention', data });
    await page.settle();
    expect(
      screen.getByRole('link', { name: 'Concurrent sessions in one checkout' }),
    ).toBeInTheDocument();
    expect(document.body).toHaveTextContent('2 sessions working or waiting in the same checkout');
    expect(document.body.innerHTML).not.toContain('checkout:a7b8c9');
    expect(document.body.innerHTML).not.toContain('path:audits');
    expect(document.body.innerHTML).not.toContain('/private/checkouts/audits');
  });

  it('a person sees concurrent worktrees separately and never treats an ended row as working', async () => {
    const data = locationBoard(3);
    for (const [i, row] of locationRows(data).entries())
      Object.assign(row, {
        state: 'working',
        project_key: 'git:audits',
        project_identity_source: 'git common directory',
        worktree: i === 1 ? 'second' : 'first',
        checkout_key: i === 1 ? 'checkout:second' : 'checkout:first',
      });
    locationRow(data, 2)['ended_at'] = 1899999999;
    const page = mountShell({ hash: '#n=attention', data });
    await page.settle();
    expect(document.body).not.toHaveTextContent('Concurrent sessions');
  });

  it.each([0, -1, 1899999000])(
    'a person reads honest member-link fallbacks with start time %s',
    async (started) => {
      const data = locationBoard(2);
      Object.assign(locationRow(data, 1), {
        project_key: 'path:other',
        title: ' \t ',
        started_at: started,
      });
      const page = mountShell({ hash: '#n=attention', data });
      await page.settle();
      const card = document.querySelector('[data-next-board-risk="collision"]') as HTMLElement;
      const stamp = started > 0 ? new Date(started * 1000).toISOString() : 'not published';
      const link = within(card).getByRole('link', {
        name: `Title not published · No worktree published · claude:audit-1 · Start time ${stamp}`,
      });
      expect(link).toHaveAttribute('href', '#n=session:audits:claude:audit-1');
      expect(within(card).getByRole('link', { name: /Audit 0/ })).toHaveTextContent(
        'Start time 2030-03-17T17:30:00.000Z',
      );
      expect(link).not.toHaveTextContent('1970-01-01');
    },
  );

  it('a person sees shared-label stops and tasks in the queues counted by the summary', async () => {
    const data = locationBoard();
    for (const row of locationRows(data).slice(0, 3)) row['finished_at'] = 1899999999;
    locationRow(data, 3)['ended_at'] = 1899999999;
    locationRow(data, 4)['tasks'] = [{ status: 'in_progress', subject: 'Inspect the next target' }];
    // Keep a real label warning present while checking it cannot own stops or tasks.
    locationRow(data, 8)['project_key'] = 'path:other';
    const page = mountShell({ hash: '#n=attention', data });
    await page.settle();
    expect(screen.getByRole('heading', { name: 'Close the loop (4)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Coming next (1)' })).toBeInTheDocument();
    expect(
      document.querySelectorAll('[data-next-attention-section="close"] > ol > li'),
    ).toHaveLength(4);
    expect(document.querySelector('[data-next-attention-section="next"]')).toHaveTextContent(
      'Inspect the next target',
    );
    expect(document.querySelector('.next-attention-brief')).toHaveTextContent(
      '4 to close the loop',
    );
  });
});
