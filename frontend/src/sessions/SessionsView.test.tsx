import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mountSessions } from './testing';
import { rowState } from './rows';
import type { ObservedSession } from '../observed';

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
      [...document.querySelectorAll('[data-next-fleet-fact] strong')].map(
        (node) => node.textContent,
      ),
    ).toEqual(['0', '0']);
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
    expect(document.querySelector('[data-next-session-drift-mark]')?.textContent).toBe(
      'Drift · 1m ago',
    );
    // Counted with the cards listed under Active now, and still not called working.
    expect(document.querySelector('[data-next-fleet-fact="active"] strong')?.textContent).toBe('1');
    expect(document.querySelector('[data-next-fleet-fact="working"] strong')?.textContent).toBe(
      '0',
    );
  });

  it('leads each row with one state word and shows the project label alone as where', async () => {
    await open(data);
    const state = (sid: string) =>
      document.querySelector(`article[data-next-session="${sid}"] [data-next-row-state]`)
        ?.textContent;
    expect(state('gate')).toBe('Waiting on you');
    expect(state('work')).toBe('Working');
    expect(state('idle-new')).toBe('Idle');
    expect(state('done')).toBe('Ended');
    const groups = [...document.querySelectorAll('[data-next-operation-group]')];
    for (const group of groups) expect(group.textContent).not.toMatch(/NOW · |QUIET/);
    expect(document.body.textContent).not.toContain('Exact location not published');
    expect(
      document.querySelector('article[data-next-session="work"] [data-next-operation-fact="where"]')
        ?.textContent,
    ).toBe('PROJECTp');
  });

  it('names the level of a departing stored reading on the drift chip', async () => {
    await open(
      board(
        [
          {
            harness: 'claude',
            sid: 'read',
            project: 'p',
            state: 'idle',
            annotation_revision: 2,
            annotation_assessment: {
              read_at: NOW - 240,
              revision_read: 2,
              criteria: { goal: { result: 'departure', cites: ['f1'], detail: '', clause: 'x' } },
            },
          },
        ],
        { annotate: true },
      ),
    );
    const mark = document.querySelector('[data-next-session-drift-mark]');
    // This tab holds no analysis for the project, so the chip says what a departure is at least, and draws
    // no meter, which would show Medium for what may be High.
    expect(mark?.textContent).toBe('Drift: Medium or higher · 4m ago');
    expect(
      mark?.querySelector('[data-next-row-drift-level]')?.getAttribute('data-next-row-drift-level'),
    ).toBe('medium_or_higher');
    expect(mark?.querySelector('.next-session-drift-pill-meter')).toBeNull();
  });

  describe('the chip and the session header name one level', () => {
    const departing = {
      harness: 'claude',
      sid: 'read',
      project: 'p',
      project_key: '/p',
      state: 'idle',
      annotation_goal: 'Ship the queue',
      annotation_line_1: 'Tests pass',
      annotation_revision: 2,
      annotation_assessment: {
        read_at: NOW - 240,
        revision_read: 2,
        criteria: { goal: { result: 'departure', cites: ['f1'], detail: '', clause: 'x' } },
      },
    };
    /* The entry the departure cites: a departure naming one the record does not hold is refused, and a
       level stands only on a departure the reading shows. */
    const said = {
      fact_id: 'f1',
      type: 'agent_message',
      by: 'agent',
      summary: 'Done: the queue ships.',
      at: NOW - 300,
      source_session: { harness: 'claude', sid: 'read' },
      evidence: { source: 'transcript', confidence: 'exact' },
    };
    const context = (level: string) => ({
      semantic: { facts: [said] },
      sources: {
        work: {
          tool_reports: [],
          analysis_levels: [
            {
              harness: 'claude',
              sid: 'read',
              revision_read: 2,
              read_at: NOW - 240,
              computed_at: NOW - 240,
              level,
              reasons: ['departure'],
              cites: ['f1'],
            },
          ],
        },
      },
    });
    const chip = () => document.querySelector('[data-next-session-drift-mark]');

    it.each([
      ['high', 'High'],
      ['medium', 'Medium'],
    ])('names %s on the chip once this tab holds the analysis', async (level, word) => {
      const page = mountSessions({
        hash: '#n=session:p:claude:read',
        data: board([departing], { annotate: true }),
        context: context(level),
      });
      await page.settle();
      const pill = document.querySelector('[data-next-drift-pill] strong')?.textContent;
      expect(pill).toBe(word);
      await act(async () => {
        page.router.navigate({ view: 'sessions' });
      });
      await page.settle();
      expect(chip()?.querySelector('strong')?.textContent).toBe(pill);
      expect(
        chip()
          ?.querySelector('[data-next-row-drift-level]')
          ?.getAttribute('data-next-row-drift-level'),
      ).toBe(level);
    });

    it('names no level for a raise beside a reading that does not depart', async () => {
      const page = mountSessions({
        hash: '#n=session:p:claude:read',
        data: board(
          [
            {
              ...departing,
              departures: [{ at: NOW - 60, revision: 2 }],
              annotation_assessment: {
                read_at: NOW - 240,
                revision_read: 2,
                criteria: {
                  goal: { result: 'consistent', cites: ['f1'], detail: '', clause: 'x' },
                },
              },
            },
          ],
          { annotate: true },
        ),
        context: context('none_or_low'),
      });
      await page.settle();
      await act(async () => {
        page.router.navigate({ view: 'sessions' });
      });
      await page.settle();
      expect(chip()?.textContent).toMatch(/^Drift · /);
      expect(chip()?.querySelector('[data-next-row-drift-level]')).toBeNull();
    });
  });

  it('shows Idle only for a published idle state', () => {
    const session = (state: unknown) =>
      ({
        isEnded: false,
        isNeeds: false,
        askKnown: false,
        isWorking: false,
        isQuiet: state === 'idle',
      }) as unknown as ObservedSession;
    expect(rowState(session('idle'))).toBe('Idle');
    expect(rowState(session(undefined))).toBe('State not published');
    expect(rowState(session('dozing'))).toBe('State not published');
  });

  it('says annotations are off, and the goal cell says so too, when the payload does not publish them', async () => {
    await open(board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }]));
    expect(document.querySelector('[data-next-operation-fact="goal"]')?.textContent).toBe(
      'GOALAnnotations off',
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
    expect(goal('typed')?.textContent).toBe('GOAL · YOUR WORDSShip the queue');
    expect(goal('typed')?.querySelector('a')?.getAttribute('href')).toBe(
      '#n=session:p:claude:typed',
    );
    expect(goal('drafted')?.textContent).toBe('GOAL · YOUR FIRST PROMPTDo the thing');
    expect(goal('empty')?.textContent).toBe('GOALAdd a goal');
    expect(goal('empty')?.querySelector('a')?.classList.contains('next-absence')).toBe(true);
  });

  it('says no session has been checked while checks are visible and none exists', async () => {
    await open(
      board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }], {
        annotate: true,
        reading_routes: { claude: { provider: 'claude' } },
      }),
    );
    expect(document.querySelector('[data-next-sessions-orientation]')).toBeInTheDocument();
    document.body.innerHTML = '';
    await open(
      board(
        [{ harness: 'claude', sid: 'a', project: 'p', state: 'idle', departure_checked: true }],
        { annotate: true },
      ),
    );
    expect(
      document
        .querySelector('[data-next-sessions-orientation]')
        ?.textContent.match(/No session has been checked/),
    ).toBeNull();
  });

  it('says who a held request is addressed to', async () => {
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
    const blocked = (sid: string) =>
      document.querySelector(
        `article[data-next-session="${sid}"] [data-next-operation-fact="blocked"] small`,
      )?.textContent;
    expect(blocked('a')).toBe('BLOCKED · NEEDS YOU');
    expect(blocked('b')).toBe('BLOCKED · CAPTAIN');
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
    const summary = screen.getByRole('button', { name: 'How Intent and drift works' });
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
    fireEvent.click(document.querySelector('a[data-next-goal-focus]') as Element);
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
  it('reports the same running and blocked sessions in the header as the rows show', async () => {
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
    expect(document.querySelector('.next-running')?.textContent).toContain(
      '1 running · 2 subagents observed',
    );
    expect(document.querySelector('.next-gate')?.textContent).toBe('1 reported block');
    expect(document.querySelector('[data-next-fleet-fact="reported-blocks"]')).toBeNull();
  });
});

describe('the Sessions first step', () => {
  it.each([
    { annotate: false, reading_routes: { claude: { provider: 'claude' } } },
    {
      annotate: true,
      annotate_unreadable: 'Store unreadable',
      reading_routes: { claude: { provider: 'claude' } },
    },
    { annotate: true, reading_routes: { claude: { provider: '' } } },
  ])(
    'keeps a truthful orientation and how-to when analysis is unavailable: %j',
    async (capabilities) => {
      await open(
        board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }], capabilities),
      );
      const orientation = document.querySelector('[data-next-sessions-orientation]');
      expect(orientation?.textContent).toBe(
        'Open a session to see what it is doing and where it stands.',
      );
      expect(document.querySelectorAll('.next-operations-header > p')).toHaveLength(1);
      expect(
        screen.getByRole('button', { name: 'How Intent and drift works' }),
      ).toBeInTheDocument();
    },
  );
  it('merges the unchecked clause into one orientation paragraph when analysis is available', async () => {
    await open(
      board([{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }], {
        annotate: true,
        reading_routes: { claude: { provider: 'claude' } },
      }),
    );
    expect(document.querySelector('[data-next-sessions-orientation]')?.textContent).toBe(
      'Open a session, set its goal and press Analyze drift to see how far it moved from it. No session has been checked for drift yet; open one to check it.',
    );
    expect(document.querySelectorAll('.next-operations-header > p')).toHaveLength(1);
  });
  it.each([false, true])(
    'keeps orientation and the shared how-to when a checked session exists: %s',
    async (checked) => {
      await open(
        board(
          [
            {
              harness: 'claude',
              sid: 'a',
              project: 'p',
              state: 'idle',
              departure_checked: checked,
            },
          ],
          { annotate: true, reading_routes: { claude: { provider: 'claude' } } },
        ),
      );
      expect(document.querySelector('[data-next-sessions-orientation]')).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'How Intent and drift works' }),
      ).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'How rows are split' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Goal sources' })).toBeNull();
      expect(document.querySelector('[data-next-fleet-fact="requests"]')).toBeNull();
      expect(document.querySelector('[data-next-fleet-fact="reported-blocks"]')).toBeNull();
    },
  );
  it.each(['working', 'idle'])(
    'opens a saved goal in one press and focuses its box for %s',
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
      expect(document.activeElement?.getAttribute('data-next-focus')).toBe(
        'held:claude:saved:goal',
      );
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
      document.querySelector(
        `article[data-next-session="${sid}"] [data-next-operation-fact="where"]`,
      )?.textContent;
    expect(facts('s1')).toContain('one/compass');
    expect(facts('s2')).toContain('one/compass');
    expect(facts('s1')).toContain('worktree haiku-a');
    expect(facts('s2')).toContain('worktree haiku-b');
    // A main checkout publishes no worktree, so no worktree is drawn for it.
    expect(facts('s3')).toBe('PROJECTone/compass');
  });
});
