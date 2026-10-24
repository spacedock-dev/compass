import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { mountSessions, type AnswerScript } from './testing';
import { answerNotesFor } from './heldState';

const NOW = 5000;
const ASK = {
  id: 'ask-1',
  harness: 'claude',
  session_id: 'one',
  project: 'p',
  question: 'Approve the plan?',
  options: ['Yes', 'No', 'Later'],
  age_sec: 90,
};
const board = (sessions: unknown[], extra: Record<string, unknown> = {}) => ({
  generated: NOW,
  sessions,
  ...extra,
});
const ONE = {
  harness: 'claude',
  sid: 'one',
  project: 'p',
  title: 'Retry queue',
  state: 'needs_input',
  blocked_since: NOW - 120,
};
const ROUTE = '#n=session:p:claude:one';

describe('the session age in the header', () => {
  it('a reader sees the published start and its exact local time on the existing identity line', async () => {
    const start = 1900000000;
    await open({
      ...board([{ ...ONE, started_at: start, first_prompt_at: start - 600 }]),
      generated: start + 23 * 3600,
    });
    const age = screen.getByText('Started about 23h 0m ago');
    expect(age.closest('.next-session-identity')).not.toBeNull();
    expect(age.getAttribute('title')).toBe(`Started: ${new Date(start * 1000).toLocaleString()}`);
  });
  it('a reader with only a first message sees that honest source in the tooltip', async () => {
    await open(board([{ ...ONE, first_prompt_at: 1000 }]));
    const age = screen.getByText('Started about 1h 6m ago');
    expect(age.getAttribute('title')).toBe(
      `From the first message in the record: ${new Date(1000000).toLocaleString()}`,
    );
  });
  it('a reader sees no guessed age when neither start nor first message time is published', async () => {
    await open(board([ONE]));
    expect(document.querySelector('[data-session-age]')).toBeNull();
    expect(screen.queryByText(/Started about/)).toBeNull();
  });
});

describe('the worktree in the header', () => {
  it('a reader sees which worktree the session ran in beside its project', async () => {
    await open(board([{ ...ONE, worktree: 'haiku-a' }]));
    const identity = document.querySelector('.next-session-identity');
    expect(identity?.textContent).toContain('worktree haiku-a');
  });
  it('a main checkout draws no worktree', async () => {
    await open(board([ONE]));
    expect(document.querySelector('.next-session-identity')?.textContent).not.toContain('worktree');
  });
});

const RATED = {
  harnesses: [{ key: 'claude', label: 'Claude Code', reports_rate: true, discovered: true }],
};
const header = () => document.querySelector('.next-session-detail-header') as HTMLElement;

describe('the header as one line', () => {
  it('a working session names its token rate, its state, its activity and its turn in one row', async () => {
    await open(
      board(
        [
          {
            ...ONE,
            state: 'working',
            blocked_since: undefined,
            rate_per_min: 1450,
            state_detail: 'running Bash',
            turn: { elapsed_h: '54s' },
          },
        ],
        RATED,
      ),
    );
    const bar = header().querySelector('.next-session-detail-bar') as HTMLElement;
    expect(bar.querySelector('.next-session-identity')).not.toBeNull();
    expect(bar.querySelector('.next-session-detail-meta')).not.toBeNull();
    expect(bar.textContent).toContain('1,450 tokens/min');
    expect(bar.textContent).toContain('running Bash');
  });
  it('an idle session shows no token rate', async () => {
    await open(
      board([{ ...ONE, state: 'idle', blocked_since: undefined, rate_per_min: 4106 }], RATED),
    );
    expect(header().textContent).not.toContain('tokens/min');
  });
  it('an ended session shows no token rate', async () => {
    await open(
      board(
        [
          {
            ...ONE,
            state: 'working',
            blocked_since: undefined,
            rate_per_min: 4106,
            ended_at: NOW - 30,
          },
        ],
        RATED,
      ),
    );
    expect(header().textContent).not.toContain('tokens/min');
  });
  it('a finished turn reads when it ended and that the session waits for the reader', async () => {
    const finished = new Date(2030, 0, 2, 11, 0, 0).getTime() / 1000;
    await open(
      board(
        [
          {
            ...ONE,
            state: 'idle',
            blocked_since: undefined,
            finished_at: finished,
            state_detail: 'awaiting your message',
          },
        ],
        { generated: finished + 60 },
      ),
    );
    expect(document.body.textContent).toContain('Turn ended 11:00 · waiting for you');
    expect(document.body.textContent).not.toContain('idle · awaiting your message');
  });
});

describe('a title that is only an identifier', () => {
  it('falls back to the session goal instead of showing the key as the title', async () => {
    await open(
      board([
        {
          ...ONE,
          title: 'DRC-4929',
          state: 'idle',
          blocked_since: undefined,
          instruction: { label: 'asked', text: 'Fix the retry queue backoff', at: NOW - 60 },
        },
      ]),
    );
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(
      'Fix the retry queue backoff',
    );
  });
  it('keeps a real title', async () => {
    await open(board([{ ...ONE, title: 'Retry queue backoff' }]));
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Retry queue backoff');
  });
});

async function open(
  data: unknown,
  options: {
    answer?: AnswerScript;
    hash?: string;
    strict?: boolean;
    focusCapability?: string;
  } = {},
) {
  const page = mountSessions({ hash: options.hash ?? ROUTE, data, ...options });
  await page.settle();
  return page;
}

const failure = () => document.querySelector('.next-session-answer-failure');
const expectPoliteFailure = (notice: Element | null) => {
  expect(notice).not.toBeNull();
  expect(notice?.getAttribute('role')).toBe('status');
  expect([null, 'polite']).toContain(notice?.getAttribute('aria-live'));
};

it('has no session copy controls, including beside a stored departure with a resume command', async () => {
  const page = await open(
    board(
      [
        {
          ...ONE,
          resume_id: 'abc-1',
          departures: [{ at: 100, revision: 1, constraint: 'goal', reading: 'r' }],
        },
      ],
      { annotate: true },
    ),
    { focusCapability: 'minted' },
  );
  expect(document.querySelector('[data-copy-kind]')).toBeNull();
  expect(document.body.textContent).not.toContain('No resume command');
  expect(document.body.textContent).toContain('No terminal to raise');
  await act(async () => {
    page.router.navigate({ view: 'sessions' });
  });
  await page.settle();
  expect(document.querySelector('.next-operation-row [data-copy-kind]')).toBeNull();
});

describe('answering a held request', () => {
  const asked = () => board([ONE], { ask: true, asks: [ASK] });

  it('shows every exact request in payload order, each with its options in order', async () => {
    await open(
      board([ONE], {
        ask: true,
        asks: [ASK, { ...ASK, id: 'ask-2', question: 'Second?', options: ['A', 'B'] }],
      }),
    );
    const cards = [...document.querySelectorAll('[data-next-session-ask]')];
    expect(cards.map((card) => card.getAttribute('data-next-session-ask'))).toEqual([
      'ask-1',
      'ask-2',
    ]);
    expect(
      cards.map((card) =>
        within(card as HTMLElement)
          .getAllByRole('button')
          .map((button) => button.textContent),
      ),
    ).toEqual([
      ['Yes', 'No', 'Later'],
      ['A', 'B'],
    ]);
    expect(
      cards.map((card) => card.querySelector('.next-session-ask-question')?.textContent),
    ).toEqual(['Approve the plan?', 'Second?']);
  });

  it('posts one numeric option index, never the option, and exactly once per press', async () => {
    const page = await open(asked());
    fireEvent.click(screen.getByRole('button', { name: 'No' }));
    await page.settle();
    const posts = page.posts();
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({
      method: 'POST',
      url: '/api/answer',
      body: { id: 'ask-1', index: 1 },
    });
    expect(Object.keys(posts[0]?.body as object).sort()).toEqual(['id', 'index']);
    expect(typeof (posts[0]?.body as { index: unknown }).index).toBe('number');
  });

  it('sends nothing on mount, under StrictMode, on a poll, or on a reconnect', async () => {
    const page = await open(asked());
    await page.poll(asked());
    await page.poll(asked());
    page.clock.advance(60_000);
    await page.settle();
    expect(page.posts()).toEqual([]);
  });

  it('answers a second press, while the first is in flight, with nothing, and shows the busy control', async () => {
    const page = await open(asked(), { answer: { kind: 'hold' } });
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await page.settle();
    const busy = document.querySelector('[data-next-answer-index="0"]');
    expect(busy?.getAttribute('aria-disabled')).toBe('true');
    expect(busy?.getAttribute('aria-busy')).toBe('true');
    expect(busy?.hasAttribute('data-next-pending')).toBe(true);
    expect(busy?.textContent).toContain('Sending…');
    fireEvent.click(document.querySelector('[data-next-answer-index="1"]') as Element);
    fireEvent.click(busy as Element);
    await page.settle();
    expect(page.posts()).toHaveLength(1);
    await page.release(new Response(JSON.stringify({ ok: true, answered: true }), { status: 200 }));
    expect(document.querySelector('[data-next-pending]')).toBeNull();
  });

  it('holds the busy control until the refresh after a confirmed answer lands, so no second option can follow it', async () => {
    const page = await open(asked());
    page.state.holdData = true;
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await page.settle();
    expect(page.posts()).toHaveLength(1);
    // The server confirmed, but the board that drops the question has not arrived: the card is still on screen.
    expect(document.querySelector('[data-next-answer-index="0"]')?.getAttribute('aria-busy')).toBe(
      'true',
    );
    fireEvent.click(document.querySelector('[data-next-answer-index="1"]') as Element);
    await page.settle();
    expect(page.posts()).toHaveLength(1);
    expect(failure()).toBeNull();
    await page.releaseData();
    expect(document.querySelector('[data-next-pending]')).toBeNull();
  });

  it('keeps the question when the server did not confirm, and says so', async () => {
    for (const answer of [
      { kind: 'refuse' },
      { kind: 'status', status: 500 },
      { kind: 'not-json' },
      { kind: 'offline' },
    ] as const) {
      const page = await open(asked(), { answer });
      fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
      await page.settle();
      expect(failure()?.textContent).toBe(
        'no confirmation came back — it may already have been answered',
      );
      expect(document.querySelector('[data-next-session-ask="ask-1"]')).not.toBeNull();
      page.unmount();
    }
  });

  it('exposes one polite failure notice and retains it silently through polls', async () => {
    const page = await open(asked(), { answer: { kind: 'refuse' } });
    const additions: Element[] = [];
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof Element)) continue;
          if (node.matches('[data-slot="alert"]')) additions.push(node);
          additions.push(...node.querySelectorAll('[data-slot="alert"]'));
        }
      }
    });
    observer.observe(page.container, { childList: true, subtree: true });
    try {
      fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }));
      await page.settle();
      const notice = failure();
      expectPoliteFailure(notice);
      // The existing notice mounts with text present; this guards retention, not an initial announcement.
      expect(additions).toEqual([notice]);
      await page.poll(asked());
      await page.poll(asked());
      expect(failure()).toBe(notice);
      expect(additions).toEqual([notice]);
      expect(notice?.textContent).toBe(
        'no confirmation came back — it may already have been answered',
      );
    } finally {
      observer.disconnect();
    }
  });

  it('updates an already-mounted polite failure region once, without repeating it on polls or rerenders', async () => {
    const page = await open(asked(), { answer: { kind: 'refuse' } });
    const notes = answerNotesFor(page.shell.runtime);
    await act(async () => {
      notes.set('ask-1', 'Earlier failure');
    });
    const notice = failure();
    expectPoliteFailure(notice);
    const textNode = notice?.firstChild;
    const changes: MutationRecord[] = [];
    const observer = new MutationObserver((records) => changes.push(...records));
    observer.observe(notice as Element, {
      characterData: true,
      characterDataOldValue: true,
      childList: true,
      subtree: true,
    });
    try {
      fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }));
      await page.settle();
      expect(failure()).toBe(notice);
      expect(notice?.firstChild).toBe(textNode);
      expect(notice?.textContent).toBe(
        'no confirmation came back — it may already have been answered',
      );
      expect(changes).toHaveLength(1);
      expect(changes[0]).toMatchObject({
        type: 'characterData',
        target: textNode,
        oldValue: 'Earlier failure',
      });
      await page.poll(asked());
      await page.poll(asked());
      await act(async () => {
        notes.set('ask-1', 'no confirmation came back — it may already have been answered');
      });
      await page.settle();
      expectPoliteFailure(failure());
      expect(failure()).toBe(notice);
      expect(notice?.firstChild).toBe(textNode);
      expect(changes).toHaveLength(1);
    } finally {
      observer.disconnect();
    }
  });

  it.each([
    ['aria-live', 'off'],
    ['role', 'alert'],
  ])('rejects the failure-region mutation %s="%s"', async (attribute, value) => {
    const page = await open(asked(), { answer: { kind: 'refuse' } });
    fireEvent.click(screen.getByRole('button', { name: /^Yes$/ }));
    await page.settle();
    const notice = failure();
    expectPoliteFailure(notice);
    notice?.setAttribute(attribute, value);
    expect(() => expectPoliteFailure(notice)).toThrow();
  });

  it('clears the failure sentence when a later press is confirmed, and retires the question only when the board stops carrying it', async () => {
    const page = await open(asked(), { answer: { kind: 'refuse' } });
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await page.settle();
    expect(failure()).not.toBeNull();
    page.state.answer = { kind: 'confirm' };
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await page.settle();
    expect(failure()).toBeNull();
    // The server confirmed, but the board still carries the request: the page does not guess it away.
    expect(document.querySelector('[data-next-session-ask="ask-1"]')).not.toBeNull();
    await page.poll(board([{ ...ONE, state: 'idle' }], { ask: true, asks: [] }));
    expect(document.querySelector('[data-next-session-ask]')).toBeNull();
    expect(document.querySelector('[data-next-session-section="ask"]')).toBeNull();
  });

  it('forgets a failure note once its request has left the board', async () => {
    const page = await open(asked(), { answer: { kind: 'refuse' } });
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await page.settle();
    await page.poll(board([ONE], { ask: true, asks: [] }));
    await page.poll(asked());
    expect(failure()).toBeNull();
  });

  it('sends nothing for a request with no id, and draws a request with no options as that', async () => {
    const page = await open(board([ONE], { ask: true, asks: [{ ...ASK, id: '' }] }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    await page.settle();
    expect(page.posts()).toEqual([]);
    page.unmount();
    await open(board([ONE], { ask: true, asks: [{ ...ASK, options: [] }] }));
    expect(screen.getByText('No answer options were supplied.')).toBeInTheDocument();
  });

  it('attributes a request to the exact harness and sid, so the same sid elsewhere is not asked', async () => {
    const data = board(
      [
        { harness: 'claude', sid: 'one', project: 'p', title: 'Claude one', state: 'idle' },
        { harness: 'codex', sid: 'one', project: 'p', title: 'Codex one', state: 'idle' },
      ],
      { ask: true, asks: [{ ...ASK, harness: 'codex' }] },
    );
    await open(data, { hash: '#n=session:p:claude:one' });
    expect(document.querySelector('[data-next-session-section="ask"]')).toBeNull();
    expect(document.querySelector('.next-session-state')?.textContent).toBe('State: idle');
  });

  it('says a session holding a request needs input, and one that ended without a request is ended', async () => {
    await open(board([{ ...ONE, state: 'idle', ended_at: NOW - 30 }], { ask: true, asks: [ASK] }));
    expect(document.querySelector('.next-session-state')?.textContent).toBe('State: needs input');
    document.body.innerHTML = '';
    await open(board([{ ...ONE, state: 'working', ended_at: NOW - 30 }]));
    expect(document.querySelector('.next-session-state')?.textContent).toBe('State: ended');
    expect(document.querySelector('.next-session-detail-meta')?.textContent).toContain(
      'ended 30s ago',
    );
  });
});

describe('a session that is not in the payload', () => {
  it('says the board has not arrived before the first payload, and never "not in the payload"', async () => {
    const page = mountSessions({ hash: ROUTE, data: board([ONE]), strict: false });
    expect(screen.getByText('The first payload has not arrived yet.')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('not in the current payload');
    await page.settle();
  });

  it('names an expired identity by its harness and sid, and offers the way back', async () => {
    await open(board([ONE], { window_hours: 24 }), { hash: '#n=session:p:claude:gone' });
    expect(screen.getByText('This session is not in the current payload.')).toBeInTheDocument();
    expect(screen.getByText('claude · gone')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View all sessions' })).toBeInTheDocument();
  });
});

describe('what the page says about what it could not see', () => {
  it('says why a fact is unmeasured instead of leaving a blank', async () => {
    await open(board([{ harness: 'cursor', sid: 'x', project: 'p', state: 'working' }]), {
      hash: '#n=session:p:cursor:x',
    });
    const text = document.body.textContent ?? '';
    expect(text).toContain('Title not published');
    expect(text).toContain('Harness does not report blocks');
    expect(text).toContain('Session facts: No stop or end observed · Git state was not measured');
  });

  it('says a session that opened with a command was not named, not that no title was published', async () => {
    await open(
      board([
        {
          harness: 'claude',
          sid: 'g',
          project: 'p',
          state: 'idle',
          first_prompt: '/goal a file exists',
          first_prompt_control: true,
        },
      ]),
      { hash: '#n=session:p:claude:g' },
    );
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(
      'No name: the session opened with a command',
    );
  });

  it('draws the command-shape reports as off, with the sentence and the caveats behind one summary', async () => {
    await open(board([ONE]));
    const section = document.querySelector('[data-next-command-reports]');
    expect(section?.textContent).toContain('Command-shape reports: off');
    expect(section?.textContent).toContain('Command-shape reports are disabled for this run.');
    expect(section?.textContent).toContain('A shape match does not prove the action succeeded.');
  });

  it('lists a command report whose time is not a date without its time, where the page it ports would fail to draw at all', async () => {
    await open(
      board(
        [
          {
            ...ONE,
            command_reports: [
              { label: 'rm -rf build', tool_name: 'Bash', timestamp: 'later' },
              { label: 'ls', tool_name: 'Bash', timestamp: 1700000000 },
            ],
          },
        ],
        { irreversible_enabled: true },
      ),
    );
    const items = [...document.querySelectorAll('[data-next-command-reports] li')].map(
      (item) => item.textContent,
    );
    expect(items).toEqual([
      'Command shape reported: rm -rf buildBash',
      'Command shape reported: lsBash · 2023-11-14T22:13:20.000Z',
    ]);
  });

  it('lists workers with their own state, counts only direct children in the heading, and says how many older ones were left out', async () => {
    await open(
      board([
        {
          ...ONE,
          state: 'working',
          subagents: [
            { name: 'lead' },
            { name: 'idle one', active: false },
            { name: 'child', parent: 'lead' },
          ],
          subagents_omitted: 2,
        },
      ]),
    );
    const block = document.querySelector('[data-next-session-subagents]');
    expect(block?.querySelector('span')?.textContent).toBe(
      '1 RUNNING SUBAGENT · 1 WORKER RUNNING BENEATH',
    );
    expect(block?.querySelectorAll('.next-session-subagent')).toHaveLength(3);
    expect(block?.querySelector('.next-session-subagents-omitted')?.textContent).toBe(
      '+2 older finished workers omitted',
    );
  });
});

describe('the raise control', () => {
  const data = board([{ ...ONE, focusable: true }]);

  it('draws only with a minted capability and a terminal the session reported, and as the primary control while a request waits', async () => {
    await open(data);
    expect(document.querySelector('[data-control="raise"]')).toBeNull();
    expect(document.querySelector('.next-session-reentry-clause')?.textContent).toContain(
      'Terminal raise off',
    );
    document.body.innerHTML = '';
    await open(data, { focusCapability: 'minted' });
    const raise = document.querySelector('[data-control="raise"]');
    expect(raise).not.toBeNull();
    expect(raise?.getAttribute('data-variant') === 'raise-primary').toBe(true);
    document.body.innerHTML = '';
    await open(board([{ ...ONE, focusable: false }]), { focusCapability: 'minted' });
    expect(document.querySelector('[data-control="raise"]')).toBeNull();
    expect(document.querySelector('.next-session-reentry-clause')?.textContent).toContain(
      'No terminal to raise',
    );
  });

  it('is not drawn for a session that is not waiting, where the header offers no raise', async () => {
    await open(board([{ ...ONE, state: 'idle', focusable: true }]), { focusCapability: 'minted' });
    expect(document.querySelector('[data-control="raise"]')).toBeNull();
  });
});

describe('the checks run while the reader was away, when that lane is off', () => {
  const departed = {
    ...ONE,
    departures: [
      { at: NOW - 600, revision: 1, constraint: 'goal', reading: 'The change widened the goal.' },
    ],
  };
  const label = 'FROM THE CHECKS RUN WHILE YOU WERE AWAY';
  const part = () => document.querySelector('.next-cockpit-departure-part') as HTMLElement;

  it('prints the limit beside the rows it qualifies, as the legacy page does, so the label never reads as checks that ran', async () => {
    await open(board([departed], { unasked: false }));
    expect(part().textContent).toContain(label);
    const sentences = [...part().querySelectorAll('[data-absence="run-config"]')].map(
      (node) => node.textContent,
    );
    expect(sentences).toEqual([
      'Nothing watches for a departure on its own. Start with --unasked-readings to have Compass check a session against what you asked for while you are away.',
      'The checks that run while you were away are off for this run, so nothing new is being checked. What was already raised is still on record.',
    ]);
    expect(part().textContent).toContain('The change widened the goal.');
  });

  it('names the model off switch when that is why the lane is off', async () => {
    await open(board([departed], { unasked: false, unasked_off_reason: 'run-disabled' }));
    const first = part().querySelector('[data-absence="run-config"]')?.textContent ?? '';
    expect(first).toBe(
      'The model off switch refuses unasked checks. Restart with --unasked-readings and without either --no-harness-usage or --no-observer-model to enable them.',
    );
  });

  it('adds no off-switch sentence when the lane is on', async () => {
    await open(board([departed], { unasked: true }));
    expect(part().querySelector('[data-absence="run-config"]')).toBeNull();
    expect(part().textContent).toContain('The change widened the goal.');
  });
});
