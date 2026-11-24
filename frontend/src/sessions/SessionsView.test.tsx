import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mountSessions } from './testing';
import { rowState } from './rows';
import declared from '../../test/fixtures/declared-sessions.json';
import liveBoard from '../../test/fixtures/client-contract/data-live-row.json';
import { observe, sessionTile } from '../observed';
import { GLOSSARY } from '../language/glossary';

const NOW = 5000;
const board = (sessions: unknown[], extra: Record<string, unknown> = {}) => ({
  generated: NOW,
  sessions,
  ...extra,
});

async function open(data: unknown, options: { strict?: boolean; hash?: string } = {}) {
  const page = mountSessions({
    hash: options.hash ?? '#n=sessions',
    data,
    ...(options.strict === undefined ? {} : { strict: options.strict }),
  });
  await page.settle();
  return page;
}

const rows = (group: string) =>
  [
    ...document.querySelectorAll(
      `[data-next-operation-group="${group}"] article.next-operation-row`,
    ),
  ].map(
    (row) => `${row.getAttribute('data-next-harness')}/${row.getAttribute('data-next-session')}`,
  );

it('explains the filter counts and published history window in place', async () => {
  await open(
    board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }], {
      window_hours: 24,
      annotate: true,
    }),
  );
  expect(screen.getByRole('heading', { name: 'Earlier in the last 24 hours' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
  fireEvent.click(screen.getByRole('button', { name: 'More filters for power users' }));
  for (const [name, sentences] of [
    [
      GLOSSARY.howFilterCountsWork.plain,
      [
        'Each number beside an option is how many sessions with that value your other filters keep.',
        'Choices inside one filter widen the list; separate filters and the search narrow it.',
        'An unpublished value has its own option where the board can identify it.',
        'Tab and At a glance counts cover the whole board.',
      ],
    ],
    [
      GLOSSARY.howSessionHistoryWorks.plain,
      [
        'Recently observed is not proof the harness process is still open or closed; rows marked Ended reported their own end.',
        'Blocked sessions lead, followed by recorded departures, then working sessions.',
        'Your first prompt, or your latest where the first is not published, comes from Claude Code or Codex; other harnesses show only your typed words.',
        'A goal marked from your prompt was adopted by you.',
        'Compass saves a prompt as a goal when you choose to adopt it.',
      ],
    ],
  ] as const) {
    const trigger = screen.getByRole('button', { name });
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(trigger);
    const panel = document.getElementById(trigger.getAttribute('aria-controls') ?? '');
    for (const sentence of sentences)
      expect(panel?.textContent?.replace(/\s+/g, ' ')).toContain(sentence);
  }
});

it('shows a three-day-old row in all history without a 24-hour heading', async () => {
  await open({
    generated: 73 * 3600,
    show_all: true,
    window_hours: 24,
    sessions: [{ harness: 'codex', sid: 'old', project: 'p', state: 'ended', ended_at: 3600 }],
  });
  expect(rows('history')).toEqual(['codex/old']);
  expect(screen.getByRole('heading', { name: 'Earlier sessions' })).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Earlier in the last 24 hours' })).toBeNull();
});

it('explains what disappears from session history when annotations are off', async () => {
  await open(
    board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }], { annotate: false }),
  );
  fireEvent.click(screen.getByRole('button', { name: GLOSSARY.howSessionHistoryWorks.plain }));
  expect(screen.getByText('Annotations are off, so goals cannot be typed.')).toBeVisible();
});

describe('what the screen says when it has nothing to draw', () => {
  it('says the first payload has not arrived rather than drawing an empty board', async () => {
    mountSessions({ data: board([]), strict: false });
    expect(screen.getByText('The first payload has not arrived yet.')).toBeInTheDocument();
    expect(document.querySelector('[data-next-operation-group]')).toBeNull();
  });

  it('says the board published no session collection, which is not the same as no sessions', async () => {
    await open({ generated: NOW });
    expect(screen.getByText('The board published no session collection.')).toBeInTheDocument();
    expect(document.querySelector('[data-next-operation-group]')).toBeNull();
  });

  it('draws an empty collection as measured zeros with both groups saying they are empty', async () => {
    await open(board([]));
    expect(screen.getByText('No exact session has active evidence right now.')).toBeInTheDocument();
    expect(screen.getByText('No recent-history rows in this payload.')).toBeInTheDocument();
    expect(
      screen.getByText('You have 0 waiting on you, 0 working, 0 quiet and 0 ended on this board.'),
    ).toBeVisible();
  });

  it('failed collection and readable empty collection give different counts and search results', async () => {
    const page = await open(
      board([], {
        harnesses: [{ key: 'claude', label: 'Claude Code', discovered: true, error: 'Denied' }],
      }),
    );
    const groupCounts = () =>
      [...document.querySelectorAll('[data-sessions-group-count]')].map((node) => node.textContent);
    const stateCount = () =>
      document.querySelector('[data-filter-option="state:Working"] [data-filter-count]');
    const search = async () => {
      fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'quarterly invoices' } });
      await page.settle();
      act(() => page.clock.advance(600));
      await page.settle();
    };

    expect(groupCounts()).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    fireEvent.click(screen.getByRole('button', { name: 'More filters for power users' }));
    expect(screen.getByText('Working', { selector: '[data-filter-label]' })).toBeVisible();
    expect(stateCount()).toBeNull();
    expect(document.querySelector('[data-filter-option^="when:"] [data-filter-count]')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    await search();
    const unavailable = 'Search results are unavailable because the sources could not be read.';
    expect(document.querySelector('[data-sessions-result]')?.textContent).toBe(unavailable);
    expect(document.querySelector('#next-cockpit-cue-status')?.textContent).toBe(unavailable);
    expect(screen.queryByText('Nothing here matches.')).toBeNull();
    expect(screen.queryByText('No recent-history rows in this payload.')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));

    await page.poll(board([]));
    expect(groupCounts()).toEqual(['0 sessions', '0 sessions']);
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    expect(stateCount()?.textContent).toBe('0');
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    await search();
    const empty = document.querySelector('[data-sessions-nothing]') as HTMLElement;
    expect(within(empty).getByText('Nothing here matches.')).toBeVisible();
    expect(document.querySelector('#next-cockpit-cue-status')?.textContent).toBe(
      'Nothing here matches.',
    );
  });

  it('names a harness whose store could not be read, so its absence is not read as no sessions', async () => {
    await open(
      board([], {
        harnesses: [
          { key: 'codex', label: 'Codex', error: 'denied' },
          { key: 'claude', label: 'Claude Code' },
        ],
      }),
    );
    const note = document.querySelector('[data-next-source-gaps]');
    expect(note?.textContent).toContain('Codex: Harness source could not be read');
    expect(note?.textContent).not.toContain('Claude Code');
  });
});

describe('the groups', () => {
  const data = board(
    [
      { harness: 'claude', sid: 'idle-new', project: 'p', state: 'idle', last_activity: NOW - 5 },
      { harness: 'claude', sid: 'work', project: 'p', state: 'working', active: true },
      { harness: 'codex', sid: 'gate', project: 'q', state: 'needs_input' },
      { harness: 'claude', sid: 'idle-old', project: 'p', state: 'idle', last_activity: NOW - 500 },
      {
        harness: 'claude',
        sid: 'done',
        project: 'p',
        state: 'working',
        active: true,
        ended_at: NOW - 20,
      },
    ],
    { annotate: true },
  );

  it('puts a blocked session first, then the working one, and sends an ended session to history even though its state still says working', async () => {
    await open(data);
    expect(rows('active')).toEqual(['codex/gate', 'claude/work']);
    // The lanes keep the working lane ahead of the idle one, and an ended row is no longer active, so it leads history.
    expect(rows('history')).toEqual(['claude/done', 'claude/idle-new', 'claude/idle-old']);
  });

  it('says a history row’s end and git facts once, keeping every measured one', async () => {
    await open(
      board([
        // A stop with git unmeasured, a clean stop, a dirty stop with a count, and the three kinds of end.
        { harness: 'claude', sid: 'stop', project: 'p', state: 'idle', finished_at: NOW - 60 },
        {
          harness: 'claude',
          sid: 'stop-clean',
          project: 'p',
          state: 'idle',
          finished_at: NOW - 60,
          dirty: false,
        },
        {
          harness: 'claude',
          sid: 'stop-dirty',
          project: 'p',
          state: 'idle',
          finished_at: NOW - 60,
          dirty: true,
          changed: 3,
        },
        { harness: 'claude', sid: 'end', project: 'p', ended_at: NOW - 20 },
        { harness: 'claude', sid: 'end-clean', project: 'p', ended_at: NOW - 20, dirty: false },
      ]),
    );
    const facts = (sid: string) =>
      document.querySelector(`[data-next-session="${sid}"] [data-next-row-outcome]`)?.textContent ??
      null;
    expect(facts('stop')).toBe('Stop observed');
    expect(facts('stop-clean')).toBe('Stop observed; git state clean');
    expect(facts('stop-dirty')).toBe('Stop observed with uncommitted work · 3 changed entries');
    // A bare end is the tile, the descriptor's end age and the Now line; nothing repeats it.
    expect(facts('end')).toBeNull();
    expect(facts('end-clean')).toBe('Git state reported clean');
    for (const sid of ['stop', 'stop-clean', 'stop-dirty', 'end', 'end-clean']) {
      const row = document.querySelector(`[data-next-session="${sid}"]`);
      expect(row?.textContent, sid).not.toMatch(
        /git state not measured|Git state was not measured|Uncommitted work observed/,
      );
      expect(row?.textContent?.match(/git state|Git state/gi)?.length ?? 0).toBeLessThanOrEqual(1);
    }
    expect(
      within(document.querySelector('[data-next-session="end"]') as HTMLElement).getByText(
        'Session reported its own end',
      ),
    ).toBeVisible();
  });

  it('spells out the elapsed time on quiet and ended rows', async () => {
    await open(data);
    expect(screen.getByText('last active 5 seconds ago')).toBeVisible();
    expect(screen.getByText('ended 20 seconds ago')).toBeVisible();
  });

  it.each([
    [NOW, NOW + 86400],
    [0, NOW],
    [NOW, 1e100],
  ])(
    'shows a reported end without an unusable age against %s for %s',
    async (generated, endedAt) => {
      await open(
        board([{ harness: 'claude', sid: 'done', project: 'p', ended_at: endedAt }], { generated }),
      );
      expect(rows('history')).toEqual(['claude/done']);
      expect(screen.getByText('Session reported its own end')).toBeVisible();
      expect(screen.queryByText(/ended \d+ .* ago/)).toBeNull();
    },
  );

  it('keeps a finished run and a quiet session without an age when their observations are in the future', async () => {
    await open(
      board([
        {
          harness: 'codex',
          sid: 'run',
          project: 'p',
          state: 'idle',
          headless: true,
          turn_end_at: NOW + 10,
        },
        { harness: 'claude', sid: 'quiet', project: 'p', state: 'idle', last_activity: NOW + 10 },
      ]),
    );
    expect(screen.getByText('run finished', { exact: true })).toBeVisible();
    expect(screen.queryByText(/last active \d+ .* ago/)).toBeNull();
  });

  it('keeps one sid under two harnesses as two rows, each opening its own exact route', async () => {
    await open(
      board([
        { harness: 'claude', sid: 'shared', project: 'p', title: 'Claude one', state: 'idle' },
        { harness: 'codex', sid: 'shared', project: 'p', title: 'Codex one', state: 'idle' },
      ]),
    );
    const links = [...document.querySelectorAll('a.next-operation-route')].map((link) =>
      link.getAttribute('href'),
    );
    expect(links).toEqual(['#n=session:p:claude:shared', '#n=session:p:codex:shared']);
    expect(document.querySelectorAll('.next-operation-collision')).toHaveLength(2);
  });

  it('promotes a session holding a recorded departure over one that is only quiet, and does not call it running', async () => {
    const withDeparture = {
      harness: 'claude',
      sid: 'raised',
      project: 'p',
      state: 'idle',
      departures: [{ at: NOW - 60, revision: 1 }],
      annotation_revision: 1,
    };
    await open(
      board([{ harness: 'claude', sid: 'plain', project: 'p', state: 'idle' }, withDeparture], {
        annotate: true,
      }),
    );
    expect(rows('active')).toEqual(['claude/raised']);
    const raised = document.querySelector('article[data-next-session="raised"]');
    expect(raised?.querySelector('[data-variant="progress"]')).toBeNull();
    expect(document.querySelector('[data-next-row-drift-level]')).toBeNull();
    const glance = within(screen.getByRole('region', { name: 'At a glance' }));
    expect(glance.getByRole('button', { name: /Working now 0/ })).toBeVisible();
    expect(glance.getByRole('link', { name: /Worth a look 0/ })).toBeVisible();
  });

  it('words a session that opened with a command as the page heading does, on its row and its link', async () => {
    await open(
      board([
        {
          harness: 'claude',
          sid: 'cmd',
          project: 'p',
          state: 'idle',
          first_prompt: '/goal a file exists',
          first_prompt_control: true,
        },
      ]),
    );
    const row = document.querySelector('article[data-next-session="cmd"]');
    expect(row?.textContent).toContain('No name: the session opened with a command');
    expect(row?.textContent).not.toContain('Title not published');
    expect(row?.querySelector('a.next-operation-route')?.getAttribute('aria-label')).toContain(
      'No name: the session opened with a command',
    );
  });

  it('names the state tile and puts the project in the descriptor under the title, with no column strip', async () => {
    await open(data);
    for (const [sid, name] of [
      ['gate', 'Waiting on you'],
      ['work', 'Working'],
      ['done', 'Ended'],
    ] as const) {
      const row = document.querySelector<HTMLElement>(`article[data-next-session="${sid}"]`);
      if (!row) throw new Error(`Missing row ${sid}`);
      expect(within(row).getByRole('img', { name })).toBeVisible();
    }
    const groups = [...document.querySelectorAll('[data-next-operation-group]')];
    for (const group of groups) expect(group.textContent).not.toMatch(/NOW · |QUIET/);
    expect(document.body.textContent).not.toContain('Exact location not published');
    expect(
      document.querySelector('article[data-next-session="work"] [data-next-row-descriptor]')
        ?.textContent,
    ).toBe('claude · p · start time not published');
    expect(
      document.querySelector('article[data-next-session="done"] [data-next-row-descriptor]')
        ?.textContent,
    ).toBe('claude · p · start time not published · ended 20 seconds ago');
    expect(
      document.querySelectorAll(
        '.next-operations-columns, [data-next-operation-fact="where"], [data-next-operation-fact="next"], [data-next-operation-fact="blocked"]',
      ),
    ).toHaveLength(0);
  });

  it('says how long ago each session started, and that a start was not published', async () => {
    await open(
      board([
        {
          harness: 'claude',
          sid: 'a',
          project: 'acme/api',
          state: 'working',
          started_at: NOW - 4500,
        },
        { harness: 'claude', sid: 'b', project: 'acme/api', state: 'working' },
        // A start ahead of the board's clock has no age to give, so it is left out rather than guessed.
        {
          harness: 'claude',
          sid: 'c',
          project: 'acme/api',
          state: 'working',
          started_at: NOW + 60,
        },
      ]),
    );
    const descriptor = (sid: string) =>
      document.querySelector(`article[data-next-session="${sid}"] [data-next-row-descriptor]`)
        ?.textContent;
    expect(descriptor('a')).toBe('claude · acme/api · started 1 hour 15 minutes ago');
    expect(descriptor('b')).toBe('claude · acme/api · start time not published');
    expect(descriptor('c')).toBe('claude · acme/api');
  });

  it('draws the Now line under the descriptor, with a current task standing in when nothing is published about now', async () => {
    await open(
      board([
        {
          harness: 'claude',
          sid: 'doing',
          project: 'acme/api',
          title: 'Docs pass',
          state: 'working',
          state_detail: 'writing the docs pull request',
          instruction: { label: 'asked', text: 'Write the docs' },
        },
        {
          harness: 'claude',
          sid: 'task',
          project: 'acme/api',
          title: 'Release notes',
          state: 'working',
          instruction: { label: 'asked', text: 'Draft the release notes' },
        },
        { harness: 'claude', sid: 'bare', project: 'acme/api', title: 'Bare', state: 'working' },
      ]),
    );
    const now = (sid: string) =>
      document.querySelector<HTMLElement>(
        `article[data-next-session="${sid}"] [data-next-operation-fact="now"]`,
      );
    const doing = now('doing');
    expect(doing?.textContent).toBe('writing the docs pull request');
    const descriptor = doing?.parentElement?.querySelector('[data-next-row-descriptor]');
    expect(descriptor?.nextElementSibling).toBe(doing);
    // The task keeps its own line when the Now line already says what the session is doing.
    expect(
      document.querySelector('article[data-next-session="doing"] .next-operation-assignment')
        ?.textContent,
    ).toBe('Current task · Write the docs');
    expect(now('task')?.textContent).toBe('Current task · Draft the release notes');
    expect(now('task')?.querySelector('[data-authored]')?.textContent).toBe(
      'Draft the release notes',
    );
    expect(
      document.querySelector('article[data-next-session="task"] .next-operation-assignment'),
    ).toBeNull();
    expect(now('bare')?.textContent).toBe('Activity not published');
    expect(now('bare')?.classList.contains('next-absence')).toBe(false);
  });

  const reading = {
    revision_read: 2,
    read_at: NOW - 60,
    scope: 'last-turn',
    criteria: { goal: { result: 'departure', cites: ['f1'], detail: '', clause: 'Ship it' } },
  };
  const assessed = {
    annotation_goal: 'Ship it',
    annotation_revision: 2,
    annotation_assessment: reading,
  };

  it('leaves the published departure details on the session page', async () => {
    const page = await open(
      board([{ harness: 'claude', sid: 'read', state: 'working', ...assessed }]),
    );
    const row = document.querySelector<HTMLElement>('article[data-next-session="read"]');
    if (!row) throw new Error('Missing row');
    expect(row.textContent).not.toMatch(/Slightly off course|Off course|Way off course/);
    expect(row.querySelector('[data-slot="badge"], .next-operation-progress')).toBeNull();
    expect(
      page.state.requests.some((request) => request.url.startsWith('/api/project-context')),
    ).toBe(false);
  });

  it.each([
    ['a row with no goal', {}],
    ['a Codex row without a goal', { harness: 'codex' }],
    ['a Codex row with a goal', { harness: 'codex', annotation_goal: 'Ship it' }],
    ['a saved departure', assessed],
    [
      'a non-departing reading',
      {
        ...assessed,
        annotation_assessment: {
          ...reading,
          criteria: {
            goal: { ...reading.criteria.goal, result: 'consistent with the evidence read' },
          },
        },
      },
    ],
    ['a Codex reading', { ...assessed, harness: 'codex' }],
    [
      'a withdrawn reading',
      {
        ...assessed,
        annotation_assessment: { ...reading, scope: 'withdrawn' },
      },
    ],
    ['an inaccurate reading', { ...assessed, annotation_not_accurate: true }],
    ['a mismatched revision', { ...assessed, annotation_revision: 3 }],
    ['a refused reading', { annotation_goal: 'Ship it', annotation_reading_refused: true }],
  ])('leaves the progress slot blank for %s', async (_kind, fields) => {
    await open(
      board([{ harness: 'claude', sid: 'read', state: 'working', ...fields }], { annotate: true }),
    );
    const row = document.querySelector('article[data-next-session="read"]');
    expect(row).toBeInTheDocument();
    expect(row?.querySelector('.next-operation-progress')).toBeNull();
    expect(row?.querySelector('[data-variant="progress"]')).toBeNull();
    // The progress slot holds no absence word; the goal cell's own "No goal yet" is not the progress slot.
    expect(row?.querySelector('.next-operation-identity')?.textContent).not.toMatch(
      /No goal yet|Not checked yet/,
    );
  });

  it('leaves the row blank for a live estimate before a stored check', async () => {
    const data = liveBoard.response.body;
    await open({
      ...data,
      sessions: data.sessions.map((row) =>
        row.sid === '44444444' ? { ...row, departure_checked: false } : row,
      ),
    });
    const row = document.querySelector('article[data-next-session="44444444"]');
    expect(row).toBeInTheDocument();
    expect(row?.querySelector('.next-operation-progress, [data-variant="progress"]')).toBeNull();
    expect(row?.textContent).not.toMatch(/No goal yet|Not checked yet/);
  });

  it.each([
    { annotate: false },
    { annotate: true, annotate_unreadable: 'The store cannot be read' },
  ])('omits progress copy when saved goals are unavailable (%j)', async (metadata) => {
    await open(board([{ harness: 'claude', sid: 'read', state: 'working' }], metadata));
    const row = document.querySelector('article[data-next-session="read"]');
    expect(row).toBeInTheDocument();
    expect(row?.querySelector('.next-operation-progress')).toBeNull();
  });

  it('keeps State not published in the line below the title', async () => {
    await open(
      board([{ harness: 'claude', sid: 'unpublished', title: 'Unmeasured', state: 'idle' }]),
    );
    const row = document.querySelector<HTMLElement>('article[data-next-session="unpublished"]');
    if (!row) throw new Error('Missing row');
    const title = within(row).getByRole('link', { name: 'Open session Unmeasured' });
    const absence = within(row).getByText('State not published');
    expect(title.compareDocumentPosition(absence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    /* The row still draws a tile, the neutral one, and the text line stays the row's state word. */
    const tile = within(row).getByRole('img', { name: 'State not known' });
    expect(tile.querySelector('[data-icon="state-not-known"]')).toBeInTheDocument();
    expect(tile.getAttribute('data-next-row-state')).toBeNull();
    expect(row.querySelector('[data-next-row-state]')).toBe(absence);
  });

  it('keeps Waiting on child in the line below the title', async () => {
    await open(declared.payload);
    const row = document.querySelector<HTMLElement>('article[data-next-session="parent"]');
    if (!row) throw new Error('Missing row');
    const title = within(row).getByRole('link', { name: 'Open session Coordinate release' });
    const absence = within(row).getByText(/Waiting on child/);
    expect(title.compareDocumentPosition(absence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    /* The parent is itself working, so its tile says Working; the child wait stays its state line. */
    const tile = within(row).getByRole('img', { name: 'Working' });
    expect(tile.getAttribute('data-next-row-state')).toBeNull();
    expect(row.querySelector('[data-next-row-state]')?.getAttribute('data-next-row-state')).toBe(
      'Waiting on child',
    );
  });

  it("gives every row a tile: a child wait takes the session's own state, an unpublished state the State not known tile", () => {
    const child = { harness: 'codex', sid: 'kid' };
    const sessions = observe(
      board([
        { ...child, state: 'working' },
        { harness: 'claude', sid: 'w', state: 'working', waiting_on_child: child },
        {
          harness: 'claude',
          sid: 'q',
          state: 'idle',
          finished_at: NOW - 2,
          waiting_on_child: child,
        },
        { harness: 'claude', sid: 'u', state: 'idle', waiting_on_child: child },
        { harness: 'claude', sid: 'i', state: 'idle' },
        { harness: 'claude', sid: 'x', state: 'dozing' },
        { harness: 'claude', sid: 'n' },
      ]),
    ).sessions;
    const bySid = new Map(sessions.map((session) => [session.sid, session]));
    const read = (sid: string) => {
      const session = bySid.get(sid);
      if (!session) throw new Error(`Missing ${sid}`);
      return [rowState(session), sessionTile(session)];
    };
    expect(['kid', 'w', 'q', 'u', 'i', 'x', 'n'].map(read)).toEqual([
      ['Working', 'Working'],
      ['Waiting on child', 'Working'],
      ['Waiting on child', 'Quiet'],
      ['Waiting on child', 'State not known'],
      ['State not published', 'State not known'],
      ['State not published', 'State not known'],
      ['State not published', 'State not known'],
    ]);
  });

  it('shows Quiet only for a published idle with a measured turn stop', () => {
    const states = observe(
      board([
        { harness: 'claude', sid: '1', state: 'idle', finished_at: NOW - 2 },
        { harness: 'claude', sid: '2', state: 'idle' },
        { harness: 'claude', sid: '3' },
        { harness: 'claude', sid: '4', state: 'dozing' },
      ]),
    ).sessions.map(rowState);
    expect(states).toEqual([
      'Quiet',
      'State not published',
      'State not published',
      'State not published',
    ]);
  });

  it('says annotations are off, and the goal cell says so too, when the payload does not publish them', async () => {
    await open(board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }]));
    expect(document.querySelector('[data-next-operation-fact="goal"]')?.textContent).toBe(
      'GoalAnnotations off',
    );
  });

  it('names where the goal words came from, and links an empty goal to its session', async () => {
    const claude = {
      harness: 'claude',
      sid: 'typed',
      project: 'p',
      state: 'idle',
      annotation_goal: 'Ship the queue',
    };
    const drafted = {
      harness: 'claude',
      sid: 'drafted',
      project: 'p',
      state: 'idle',
      first_prompt: 'Do the thing',
      first_prompt_at: NOW - 100,
    };
    const empty = { harness: 'cursor', sid: 'empty', project: 'p', state: 'idle' };
    await open(board([claude, drafted, empty], { annotate: true }));
    const goal = (sid: string) =>
      document.querySelector(
        `article[data-next-session="${sid}"] [data-next-operation-fact="goal"]`,
      );
    expect(goal('typed')?.textContent).toBe('Goal · your wordsShip the queue');
    expect(goal('typed')?.querySelector('a')?.getAttribute('href')).toBe(
      '#n=session:p:claude:typed',
    );
    expect(goal('drafted')?.textContent).toBe('Goal · your first promptDo the thing');
    // No goal: the absence word, and nothing to press (owner, 2026-11-24).
    expect(goal('empty')?.textContent).toBe('GoalNo goal yet');
    expect(goal('empty')?.querySelector('a, button')).toBeNull();
  });

  it('shows a held question under the Now line, behind the Waiting on you tile', async () => {
    await open(
      board(
        [
          { harness: 'claude', sid: 'a', project: 'p', state: 'idle' },
          {
            harness: 'claude',
            sid: 'b',
            project: 'p',
            state: 'idle',
            spacedock: { workflows: [] },
          },
        ],
        {
          ask: true,
          asks: [
            { id: '1', harness: 'claude', session_id: 'a', question: 'One?', options: ['y'] },
            { id: '2', harness: 'claude', session_id: 'b', question: 'Two?', options: ['y'] },
          ],
        },
      ),
    );
    for (const [sid, question] of [
      ['a', 'One?'],
      ['b', 'Two?'],
    ] as const) {
      const row = document.querySelector<HTMLElement>(`article[data-next-session="${sid}"]`);
      if (!row) throw new Error(`Missing row ${sid}`);
      expect(within(row).getByRole('img', { name: 'Waiting on you' })).toBeVisible();
      const note = row.querySelector('[data-next-row-block-note]');
      expect(note?.textContent).toBe(question);
      expect(note?.hasAttribute('data-authored')).toBe(true);
      expect(note?.classList.contains('line-clamp-3')).toBe(true);
      expect(row.querySelector('[data-next-operation-fact="now"]')?.nextElementSibling).toBe(note);
    }
  });

  it('says a reported wait once when its note only repeats the Now line', async () => {
    await open(
      board([
        {
          harness: 'claude',
          sid: 'gate',
          project: 'acme/api',
          state: 'needs_input',
          state_detail: 'Waiting for you to approve a command',
        },
      ]),
    );
    const row = document.querySelector('article[data-next-session="gate"]');
    expect(row?.querySelector('[data-next-operation-fact="now"]')?.textContent).toBe(
      'Waiting for you to approve a command',
    );
    expect(row?.querySelector('[data-next-row-block-note]')).toBeNull();
  });
});

describe('a redraw leaves the reader’s place alone', () => {
  const data = board([
    { harness: 'claude', sid: 'a', project: 'p', title: 'Alpha', state: 'working', active: true },
    { harness: 'claude', sid: 'b', project: 'p', title: 'Beta', state: 'idle' },
  ]);

  it('keeps the row nodes, an open caveat and a focused link across a poll that changes the rows', async () => {
    const page = await open(data);
    const alpha = document.querySelector('article[data-next-session="a"]');
    const summary = screen.getByRole('button', { name: GLOSSARY.howSessionHistoryWorks.plain });
    fireEvent.click(summary);
    summary.focus();
    await page.poll(
      board([{ ...(data.sessions[0] as object), state_detail: 'now different' }, data.sessions[1]]),
    );
    expect(document.querySelector('article[data-next-session="a"]')).toBe(alpha);
    expect(summary.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(summary);
  });

  it('opens a session by its exact route on a plain click, and leaves a modified click to the browser', async () => {
    const page = await open(data);
    const link = document.querySelector(
      'article[data-next-session="b"] a.next-operation-route',
    ) as HTMLAnchorElement;
    fireEvent.click(link, { ctrlKey: true });
    expect(page.router.getRoute().view).toBe('sessions');
    fireEvent.click(link);
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({
      view: 'session',
      project: 'p',
      harness: 'claude',
      session: 'b',
      from: 'sessions',
    });
  });
});

describe('the goal link opens the session at its goal', () => {
  const focused = () => document.activeElement?.getAttribute('data-next-focus');

  it('lands focus in the empty goal box when nothing is drafted, once, and not on a later visit', async () => {
    const data = board([{ harness: 'cursor', sid: 'x', project: 'p', state: 'idle' }], {
      annotate: true,
    });
    const page = await open(data);
    // A row with no goal has no goal link; opening the row itself lands in the empty goal box.
    expect(document.querySelector('a[data-next-goal-focus]')).toBeNull();
    fireEvent.click(document.querySelector('a.next-operation-route') as Element);
    await page.settle();
    expect(page.router.getRoute().view).toBe('session');
    expect(focused()).toBe('held:cursor:x:goal');
    await act(async () => {
      page.router.navigate({ view: 'sessions', project: null, session: null });
    });
    await page.settle();
    await act(async () => {
      page.router.navigate({ view: 'session', project: 'p', harness: 'cursor', session: 'x' });
    });
    await page.settle();
    expect(focused()).not.toBe('held:cursor:x:goal');
  });

  it('lands on the panel heading over an untouched draft, where a focused box could not also grow to show it whole', async () => {
    const data = board(
      [
        {
          harness: 'claude',
          sid: 'y',
          project: 'p',
          state: 'idle',
          first_prompt: 'Ship the queue',
          first_prompt_at: 100,
        },
      ],
      { annotate: true },
    );
    const page = await open(data);
    fireEvent.click(document.querySelector('a[data-next-goal-focus]') as Element);
    await page.settle();
    expect(document.activeElement?.id).toBe('next-session-intent-heading');
  });
});

describe('the header counts and the screen are one reading of one payload', () => {
  it('uses the displayed session states for Working and Waiting on you', async () => {
    await open(
      board([
        {
          harness: 'claude',
          sid: 'a',
          project: 'p',
          state: 'working',
          active: true,
          subagents: [{}, {}],
        },
        { harness: 'claude', sid: 'b', project: 'p', state: 'needs_input' },
        { harness: 'claude', sid: 'c', project: 'p', state: 'working', active: true, ended_at: 5 },
      ]),
    );
    expect(screen.getByRole('status', { name: 'Working sessions' }).textContent).toBe(
      '1 session working',
    );
    const primary = within(screen.getByRole('navigation', { name: 'Primary' }));
    expect(primary.getByRole('link', { name: 'Needs you 1' })).toBeVisible();
    expect(document.querySelector('[data-next-fleet-fact="reported-blocks"]')).toBeNull();
  });
});

describe('the Sessions first step', () => {
  it.each([false, true])(
    'keeps one summary and the history explanation with annotations set to %s',
    async (annotate) => {
      await open(
        board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }], { annotate }),
      );
      const header = screen.getByRole('heading', { name: /^Good /, level: 1 }).parentElement;
      expect(header?.querySelectorAll('p')).toHaveLength(1);
      expect(
        screen.getByRole('button', { name: GLOSSARY.howSessionHistoryWorks.plain }),
      ).toBeVisible();
      expect(screen.queryByRole('region', { name: 'Fleet facts' })).toBeNull();
    },
  );
  it.each(['working', 'idle'])(
    'opens a saved goal in one press and focuses its heading for %s',
    async (state) => {
      const page = await open(
        board(
          [
            {
              harness: 'claude',
              sid: 'saved',
              project: 'p',
              state,
              annotation_goal: 'Ship the queue',
              annotation_revision: 1,
            },
          ],
          { annotate: true },
        ),
      );
      fireEvent.click(screen.getByRole('link', { name: 'Ship the queue' }));
      await page.settle();
      expect(page.router.getRoute()).toMatchObject({ view: 'session', session: 'saved' });
      expect(document.activeElement?.getAttribute('data-next-focus')).toBe('intent:claude:saved');
    },
  );
});

describe('two sessions in two worktrees of one repository', () => {
  const tree = (sid: string, worktree: string | null) => ({
    harness: 'claude',
    sid,
    project: 'one/compass',
    project_key: 'git:abc',
    worktree,
    title: `Synthetic ${sid}`,
    state: 'working',
    last_activity: NOW - 5,
  });

  it('files both under one project and names each worktree on its row', async () => {
    await open(board([tree('s1', 'haiku-a'), tree('s2', 'haiku-b'), tree('s3', null)]));
    const facts = (sid: string) =>
      document.querySelector(`article[data-next-session="${sid}"] [data-next-row-descriptor]`)
        ?.textContent;
    expect(facts('s1')).toContain('one/compass');
    expect(facts('s2')).toContain('one/compass');
    expect(facts('s1')).toContain('worktree haiku-a');
    expect(facts('s2')).toContain('worktree haiku-b');
    // A main checkout publishes no worktree, so no worktree is drawn for it.
    expect(facts('s3')).toBe('claude · one/compass · start time not published');
  });
});

it('keeps each card preview title and reason together when a title is missing', async () => {
  await open(
    board([
      {
        harness: 'claude',
        sid: 'deploy',
        project: 'ops',
        state: 'needs_input',
        state_detail: 'Approve production?',
      },
      {
        harness: 'claude',
        sid: 'docs',
        project: 'manual',
        title: 'Edit handbook',
        state: 'needs_input',
        state_detail: 'Choose chapter?',
      },
    ]),
  );
  const card = screen.getByRole('link', { name: /Waiting on you 2/ });
  const row = document.querySelector('article[data-next-session="deploy"]');
  const title = row?.querySelector('.next-operation-route strong')?.textContent?.trim();
  expect(title).toBeTruthy();
  const deploy = within(card).getByText('Approve production?');
  const handbook = within(card).getByText('Choose chapter?');
  expect(deploy.parentElement?.textContent).toContain(title ?? '');
  expect(deploy.parentElement?.textContent).not.toContain('Edit handbook');
  expect(handbook.parentElement?.textContent).toContain('Edit handbook');
  expect(handbook.parentElement?.textContent).not.toContain('Approve production?');
});

it.each([24, 48])(
  'labels and counts the two groups using the published %i-hour window',
  async (hours) => {
    await open(
      board(
        [
          { harness: 'claude', sid: 'one', project: 'p', state: 'working', active: true },
          { harness: 'claude', sid: 'two', project: 'p' },
        ],
        { window_hours: hours },
      ),
    );
    for (const title of ['Right now', `Earlier in the last ${String(hours)} hours`]) {
      const heading = screen.getByRole('heading', { name: title });
      expect(heading.parentElement?.textContent).toContain('1 session');
    }
  },
);

it('labels the wider collection without claiming every earlier row falls inside the recent window', async () => {
  await open(
    board([{ harness: 'claude', sid: 'one', project: 'p', last_activity: 1 }], {
      window_hours: 24,
      show_all: true,
    }),
  );
  expect(screen.getByRole('heading', { name: 'Earlier sessions' })).toBeVisible();
});
