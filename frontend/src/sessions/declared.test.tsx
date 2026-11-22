import { toHaveAttribute, toHaveTextContent } from '@testing-library/jest-dom/matchers';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import fixture from '../../test/fixtures/declared-sessions.json';
import { mountSessions } from './testing';
import { filterStoreFor } from './filterStore';
import { EMPTY_FILTERS } from './filters';

expect.extend({ toHaveAttribute, toHaveTextContent });

const row = (sid: string) => document.querySelector(`[data-next-session="${sid}"]`) as HTMLElement;
async function open(hash = '#n=sessions') {
  const page = mountSessions({ data: fixture.payload, hash });
  await page.settle();
  return page;
}

describe('declared process children', () => {
  it('a reader sees the child nested after its parent and their shared words', async () => {
    await open();
    expect(
      [...document.querySelectorAll('[data-next-operation-group="active"] article')].map((n) =>
        n.getAttribute('data-next-session'),
      ),
    ).toEqual(['parent', 'child']);
    expect(row('child')).toHaveAttribute('data-declared-depth', '1');
    for (const [sid, lines] of Object.entries(fixture.expected))
      for (const line of lines) expect(row(sid)).toHaveTextContent(line);
    expect(
      within(row('child')).getByRole('link', { name: 'Child of Coordinate release' }),
    ).toHaveAttribute('href', expect.stringContaining('claude:parent'));
    expect(
      within(row('parent')).getByRole('link', { name: 'Waiting on child "Check build"' }),
    ).toHaveAttribute('href', expect.stringContaining('codex:child'));
  });
  it('a hidden headless child stays hidden while its parent still names the wait', async () => {
    const page = await open();
    await act(async () =>
      filterStoreFor(page.shell.controls).set({ ...EMPTY_FILTERS, headless: ['other'] }),
    );
    expect(row('child')).toBeNull();
    expect(row('parent')).toHaveTextContent('Waiting on child "Check build"');
  });
  it('a child still names a parent removed by filters and loses the link when it leaves the board', async () => {
    const page = await open();
    await act(async () =>
      filterStoreFor(page.shell.controls).set({ ...EMPTY_FILTERS, headless: ['headless'] }),
    );
    expect(row('parent')).toBeNull();
    expect(row('child')).toHaveTextContent('Child of Coordinate release');
    const child = {
      ...fixture.payload.sessions[0],
      declared_parent: null,
      declared_parent_state: 'not_linked',
      group: null,
      group_source: null,
    };
    await page.poll({ ...fixture.payload, sessions: [child] });
    expect(row('child')).toHaveTextContent('Declared parent is not on the board; not linked.');
    expect(within(row('child')).queryByRole('link', { name: /Child of/ })).toBeNull();
  });
  it('a parent page lists both children and uses the published waiting child', async () => {
    const other = { ...fixture.payload.sessions[0], sid: 'second', title: 'Check docs' };
    const page = mountSessions({
      data: { ...fixture.payload, sessions: [...fixture.payload.sessions, other] },
      hash: '#n=session:demo:claude:parent',
    });
    await page.settle();
    const links = screen.getByRole('region', { name: 'Linked children' });
    expect(links).toHaveTextContent('Check build');
    expect(links).toHaveTextContent('Check docs');
    expect(document.querySelector('[data-next-session-status]')).toBeNull();
    expect(
      screen.getByRole('link', { name: 'Waiting on child "Check build"' }),
    ).toBeInTheDocument();
    await page.poll({
      ...fixture.payload,
      sessions: fixture.payload.sessions.map((s) =>
        s.sid === 'child'
          ? { ...s, state: 'idle', ended_at: 1899999999 }
          : s.sid === 'parent'
            ? { ...s, state: 'idle', waiting_on_child: null }
            : s,
      ),
    });
    expect(document.querySelector('[data-next-session-status]')?.textContent ?? '').not.toContain(
      'Waiting on',
    );
    expect(screen.getByRole('region', { name: 'Linked children' })).toHaveTextContent('Ended');
  });
  it('a child page states its parent and inherited group while an unmatched declaration says not linked', async () => {
    const page = await open('#n=session:demo:codex:child');
    expect(screen.getByRole('link', { name: 'Child of Coordinate release' })).toBeInTheDocument();
    expect(
      screen.getByText((_text, node) => node?.textContent === fixture.expected.child[0]),
    ).toBeInTheDocument();
    await act(async () =>
      page.router.navigate({
        view: 'session',
        project: 'demo',
        harness: 'codex',
        session: 'unlinked',
      }),
    );
    expect(
      screen.getByText('Declared parent is not on the board; not linked.'),
    ).toBeInTheDocument();
  });
  it('a reader can filter and group by labels and keep both choices across a poll', async () => {
    const page = await open();
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    fireEvent.click(screen.getByRole('button', { name: 'More filters for power users' }));
    const popup = document.querySelector('[data-filter-facet="group"]') as HTMLElement;
    fireEvent.click(within(popup).getByRole('checkbox', { name: /release/ }));
    await page.settle();
    expect(row('unlinked')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Group by group' }));
    await page.poll(fixture.payload);
    expect(screen.getByRole('button', { name: 'Group by group' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(
      screen.getByRole('heading', {
        name: JSON.stringify(fixture.payload.sessions[0]?.group ?? ''),
      }),
    ).toBeInTheDocument();
    expect(row('unlinked')).toBeNull();
  });
});

it('keeps focus on the parent link when its child moves into recent history', async () => {
  const page = await open();
  within(row('child')).getByRole('link', { name: 'Child of Coordinate release' }).focus();
  await page.poll({
    ...fixture.payload,
    sessions: fixture.payload.sessions.map((one) =>
      one.sid === 'child' ? { ...one, active: false, state: 'idle', ended_at: 1899999999 } : one,
    ),
  });
  expect(document.activeElement).toBe(
    within(row('child')).getByRole('link', { name: 'Child of Coordinate release' }),
  );
});

it('a parent sees a linked child waiting on an exact question rather than its native idle state', async () => {
  const page = mountSessions({
    data: {
      ...fixture.payload,
      ask: true,
      asks: [{ id: 'q', harness: 'codex', session_id: 'child', question: 'Continue?' }],
      sessions: fixture.payload.sessions.map((one) =>
        one.sid === 'child' ? { ...one, state: 'idle' } : one,
      ),
    },
    hash: '#n=session:demo:claude:parent',
  });
  await page.settle();
  expect(screen.getByRole('region', { name: 'Linked children' }).textContent).toContain(
    'Waiting on you',
  );
});

it('a parent exact question remains its visible state while a child works', async () => {
  const page = mountSessions({
    data: {
      ...fixture.payload,
      ask: true,
      asks: [{ id: 'parent-q', harness: 'claude', session_id: 'parent', question: 'Ship now?' }],
    },
  });
  await page.settle();
  const state = row('parent').querySelector('[data-next-row-state]');
  expect(within(row('parent')).getByRole('img', { name: 'Waiting on you' })).toBe(state);
  expect(state).not.toHaveTextContent('Waiting on child "Check build"');
  await act(async () =>
    page.router.navigate({
      view: 'session',
      project: 'demo',
      harness: 'claude',
      session: 'parent',
    }),
  );
  expect(document.querySelector('[data-next-session-status]')).toHaveTextContent(
    'State: Waiting on you',
  );
  expect(document.querySelector('[data-next-session-status]')).not.toHaveTextContent(
    'Waiting on child "Check build"',
  );
  expect(screen.getAllByText('Ship now?')[0]).toBeInTheDocument();
});

it('a reader distinguishes a literal No group label in headings, choices and selected chips', async () => {
  const page = mountSessions({
    data: {
      ...fixture.payload,
      sessions: [
        {
          harness: 'codex',
          sid: 'literal',
          project: 'demo',
          title: 'Named label',
          state: 'idle',
          group: 'No group',
        },
        {
          harness: 'codex',
          sid: 'absent',
          project: 'demo',
          title: 'No label assigned',
          state: 'idle',
        },
      ],
    },
  });
  await page.settle();
  fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
  fireEvent.click(screen.getByRole('button', { name: 'More filters for power users' }));
  fireEvent.click(screen.getByRole('button', { name: 'Group by group' }));
  expect(screen.getByRole('heading', { name: '"No group"' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'No group' })).toBeInTheDocument();
  const popup = document.querySelector('[data-filter-facet="group"]') as HTMLElement;
  fireEvent.click(within(popup).getByRole('checkbox', { name: /^"No group"\s*1$/ }));
  await page.settle();
  expect(row('literal')).not.toBeNull();
  expect(row('absent')).toBeNull();
  expect(screen.getByRole('button', { name: /Group: "No group"/ })).toBeInTheDocument();
  fireEvent.click(within(popup).getByRole('checkbox', { name: /^No group\s*1$/ }));
  await page.settle();
  expect(row('absent')).not.toBeNull();
  expect(screen.getByRole('button', { name: /Group:.*"No group".*No group/ })).toBeInTheDocument();
});

it('keeps prompt-first child titles out of the state slot and quotes their relationship link', async () => {
  const title = 'You are verifying a fix round';
  const page = mountSessions({
    data: {
      ...fixture.payload,
      sessions: fixture.payload.sessions.map((one) =>
        one.sid === 'child' ? { ...one, title } : one,
      ),
    },
  });
  await page.settle();
  const state = row('parent').querySelector('[data-next-row-state]');
  expect(state?.textContent).toBe('Waiting on child "You are verifying a fix round"');
  expect(state).not.toHaveTextContent(/Waiting on you/i);
  expect(
    within(row('parent')).getByRole('link', {
      name: 'Waiting on child "You are verifying a fix round"',
    }),
  ).toHaveAttribute('href', expect.stringContaining('codex:child'));
  await act(async () =>
    page.router.navigate({
      view: 'session',
      project: 'demo',
      harness: 'claude',
      session: 'parent',
    }),
  );
  expect(document.querySelector('[data-next-session-status]')).toBeNull();
  expect(
    screen.getByRole('link', { name: 'Waiting on child "You are verifying a fix round"' }),
  ).toBeInTheDocument();
});
