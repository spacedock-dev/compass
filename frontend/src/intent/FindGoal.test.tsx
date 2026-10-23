import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { POLICY, ROUTE } from '../drift/testing';
import { json, mountIntent, type Handler } from './testing';
import { board, control, goalBox, SESSION_HASH, stored, text, type } from './panel.testing';

/* "Find goal" reads the reader's prompts on a press and nowhere else. The page sends one request for one press,
   holds the answer as a draft the reader may keep, edit or discard, and shows it exactly as a /goal is shown,
   with the prompts it was found in. A saved goal and a /goal both outrank it. */

const GOAL = 'The upload client retries a dropped connection and resumes, with the tests passing';
const FOUND = {
  ok: true,
  produced: true,
  why: '',
  found: {
    goal: GOAL,
    found_at: 1_760_000_500,
    cites: [
      { fact_id: 'f1', ordinal: 1, at: 100, quotes: ['add a retry to the upload client'] },
      { fact_id: 'f2', ordinal: 3, at: 200, quotes: ['make sure the tests still pass'] },
    ],
  },
  route: { label: 'Claude Code', provider: 'claude', model: 'm', harness: 'claude', vendor: 'A' },
};
const NOTHING = { ok: true, produced: false, found: null, why: 'none', route: FOUND.route };
const NOTHING_SAID = 'No clear goal in your prompts. Type one or use a prompt.';

const data = (
  session: Record<string, unknown> = {},
  store: Record<string, unknown> = {},
  extra: Record<string, unknown> = {},
) => ({
  ...board(session, store),
  reading: POLICY,
  reading_routes: { claude: ROUTE },
  ...extra,
});

const mount = (
  options: {
    readonly data?: unknown;
    readonly find?: Handler;
    readonly routes?: Record<string, Handler>;
  } = {},
) =>
  mountIntent({
    hash: SESSION_HASH,
    data: options.data ?? data(),
    routes: {
      ...(options.find ? { '/api/goal/find': options.find } : {}),
      ...(options.routes ?? {}),
    },
  });

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null) => {
  await act(async () => {
    fireEvent.click(button as Element);
  });
};
const find = () => control('goal-find');
const finds = (page: ReturnType<typeof mount>) =>
  page.allPosts().filter((p) => p.path === '/api/goal/find');
const mark = () => document.querySelector('[data-next-goal-detected]');
const source = () => text('[data-next-cockpit-goal-source]');
const note = () => text('[data-next-find-goal-note]');
const cites = () => [
  ...document.querySelectorAll<HTMLElement>('[data-next-found-cites] [data-next-cite]'),
];

describe('the Find goal button', () => {
  it('is drawn while no goal is saved and no /goal was detected, and sends nothing until pressed', async () => {
    const page = mount({ find: () => json(FOUND) });
    await settle(page);
    expect(find()).not.toBeNull();
    expect(find()?.textContent).toBe('Find goal');
    for (const generated of [1100, 1200])
      await page.poll({ ...(page.state.data as object), generated });
    await page.go('#n=intent');
    await page.go(SESSION_HASH);
    await settle(page);
    expect(page.allPosts()).toEqual([]);
  });

  it('is absent once a goal is saved', async () => {
    const page = mount({ data: data({}, { goal: 'My own goal', revision: 1 }) });
    await settle(page);
    expect(find()).toBeNull();
  });

  it('is absent where a /goal was detected', async () => {
    const page = mount({
      data: data({ session_goal: { text: 'The findings file exists', at: 500 } }),
    });
    await settle(page);
    expect(find()).toBeNull();
  });

  it('goes when a goal is saved or a /goal arrives while the page is open', async () => {
    const page = mount();
    await settle(page);
    expect(find()).not.toBeNull();
    await page.poll(data({ session_goal: { text: 'The findings file exists', at: 500 } }));
    expect(find()).toBeNull();
  });
});

describe('a press', () => {
  it('sends one request that names the session, its reader and the press, and nothing else', async () => {
    const page = mount({ find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(finds(page)).toHaveLength(1);
    expect(finds(page)[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      provider: 'claude',
      model: 'm',
      press: true,
      observer_model: 1,
    });
    expect(page.allPosts()).toHaveLength(1);
  });

  it('shows a busy state while it runs, and a second press while it runs sends nothing', async () => {
    const page = mount({ find: () => 'hold' });
    await settle(page);
    await press(find());
    await page.settle();
    expect(find()?.getAttribute('aria-busy')).toBe('true');
    await press(find());
    expect(finds(page)).toHaveLength(1);
    await page.release('/api/goal/find', json(FOUND));
    await settle(page);
    expect(find()).toBeNull();
  });

  it('fills the Goal field with the found goal, marks it detected and names where it came from', async () => {
    const page = mount({ find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(goalBox().value).toBe(GOAL);
    expect(mark()?.textContent).toBe('Goal detected');
    expect(source()).toMatch(/^Found in your prompts at \d\d:\d\d · not saved$/);
    expect(text('[data-next-intent-status]')).toBe('Draft');
    expect(find()).toBeNull();
  });

  it('cites each prompt it quotes by its entry number, as the Drift card cites entries', async () => {
    const page = mount({ find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(cites().map((cite) => cite.textContent)).toEqual(['[1]', '[3]']);
    expect(cites().map((cite) => cite.getAttribute('data-next-cite'))).toEqual(['f1', 'f2']);
    expect(cites().map((cite) => cite.getAttribute('aria-label'))).toEqual([
      'Show #1 in Full activity for the detected goal',
      'Show #3 in Full activity for the detected goal',
    ]);
  });

  it('shows the quoted words under the entry number they were found in, so the goal ties to the prompt', async () => {
    const page = mount({ find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    const quotes = [...document.querySelectorAll<HTMLElement>('[data-next-found-quote]')];
    expect(quotes.map((quote) => quote.textContent)).toEqual([
      '#1 “add a retry to the upload client”',
      '#3 “make sure the tests still pass”',
    ]);
    type(goalBox(), `${GOAL}, and the report is linked`);
    expect(document.querySelector('[data-next-found-quote]')).toBeNull();
  });

  it('groups several quoted sentences of one prompt under one entry number', async () => {
    const found = {
      ...FOUND.found,
      cites: [
        { fact_id: 'f1', ordinal: 1, at: 100, quotes: ['first sentence', 'second sentence'] },
        { fact_id: 'f1', ordinal: 1, at: 100, quotes: ['third sentence'] },
        { fact_id: 'f2', ordinal: 3, at: 200, quotes: ['make sure the tests still pass'] },
      ],
    };
    const page = mount({ find: () => json({ ...FOUND, found }) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(cites().map((cite) => cite.textContent)).toEqual(['[1]', '[3]']);
    const quotes = [...document.querySelectorAll<HTMLElement>('[data-next-found-quote]')];
    expect(quotes.map((quote) => quote.textContent)).toEqual([
      '#1 “first sentence” “second sentence” “third sentence”',
      '#3 “make sure the tests still pass”',
    ]);
  });

  it('is replaced by an edit: the mark, the line and the citations go with the found words', async () => {
    const page = mount({ find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    type(goalBox(), `${GOAL}, and the report is linked`);
    expect(mark()).toBeNull();
    expect(cites()).toEqual([]);
    expect(source()).toBe('Your edit of the goal found in your prompts · not saved');
    expect(find()).not.toBeNull();
    type(goalBox(), 'Something else entirely');
    expect(source()).toBe('You typed this · not saved');
  });

  it('is saved as the words in the box and nothing more, by Save intent', async () => {
    const page = mount({ find: () => json(FOUND), routes: { '/api/annotate': () => stored(1) } });
    await settle(page);
    await press(find());
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts().filter((post) => post.path === '/api/annotate')[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      goal: GOAL,
      expected_revision: 0,
    });
  });

  it('says nothing was found beside the button and leaves the Goal field as it was', async () => {
    const page = mount({ find: () => json(NOTHING) });
    await settle(page);
    const before = goalBox().value;
    await press(find());
    await settle(page);
    expect(note()).toBe(NOTHING_SAID);
    expect(goalBox().value).toBe(before);
    expect(before).toBe('Ship the queue worker');
    expect(mark()).toBeNull();
    expect(find()).not.toBeNull();
    expect(page.allPosts().filter((post) => post.path !== '/api/goal/find')).toEqual([]);
  });

  it('says there is nothing to read where the session has no prompts of the reader’s', async () => {
    const page = mount({ find: () => json({ ...NOTHING, why: 'no-prompts' }) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(note()).toMatch(/no prompts of yours/i);
  });

  it('clears its note when the reader types', async () => {
    const page = mount({ find: () => json(NOTHING) });
    await settle(page);
    await press(find());
    await settle(page);
    type(goalBox(), 'Something typed');
    expect(note()).toBe('');
  });
});

describe('while model calls are paused or the day is spent', () => {
  it('sends nothing when the board says calls are paused, and says so', async () => {
    const paused = { ...POLICY, consent: false, off: true, reason: 'model-calls-paused' };
    const page = mount({ data: data({}, {}, { reading: paused }), find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(finds(page)).toEqual([]);
    expect(note()).toMatch(/paused/i);
    expect(goalBox().value).toBe('Ship the queue worker');
  });

  it('says so when the server refuses a press the board had not yet marked paused', async () => {
    const reading = { ...POLICY, consent: false, off: true, reason: 'model-calls-paused' };
    const page = mount({ find: () => json({ ok: false, produced: false, reading }, 403) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(finds(page)).toHaveLength(1);
    expect(note()).toMatch(/paused/i);
    expect(goalBox().value).toBe('Ship the queue worker');
  });

  it('says the day’s limit is reached and when it lifts, and changes nothing', async () => {
    const reading = {
      ...POLICY,
      reason: 'daily-cap',
      used: 10,
      limit: 10,
      retry_at: 1_760_090_000,
    };
    const page = mount({ find: () => json({ ok: false, produced: false, reading }, 429) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(note()).toMatch(/limit reached/i);
    expect(goalBox().value).toBe('Ship the queue worker');
  });

  it('sends nothing, and says why, where no reader is published for the session', async () => {
    const page = mount({ data: data({}, {}, { reading_routes: {} }), find: () => json(FOUND) });
    await settle(page);
    await press(find());
    await settle(page);
    expect(finds(page)).toEqual([]);
    expect(note()).not.toBe('');
  });
});

describe('what a found goal does not outrank', () => {
  it('yields to a /goal that arrived while the search ran, and shows the /goal', async () => {
    const page = mount({ find: () => 'hold' });
    await settle(page);
    await press(find());
    await page.settle();
    await page.poll(data({ session_goal: { text: 'The findings file exists', at: 500 } }));
    await page.release('/api/goal/find', json(FOUND));
    await settle(page);
    expect(goalBox().value).toBe('The findings file exists');
    expect(text('[data-next-goal-detected]')).toBe('Goal detected');
    expect(source()).toMatch(/^From your \/goal/);
    expect(cites()).toEqual([]);
  });

  it('yields to a goal saved while the search ran', async () => {
    const page = mount({ find: () => 'hold' });
    await settle(page);
    await press(find());
    await page.settle();
    await page.poll(data({}, { goal: 'My own goal', revision: 1 }));
    await page.release('/api/goal/find', json(FOUND));
    await settle(page);
    expect(goalBox().value).toBe('My own goal');
    expect(mark()).toBeNull();
    expect(cites()).toEqual([]);
  });

  it('leaves words the reader began typing while it ran, and says it did', async () => {
    const page = mount({ find: () => 'hold' });
    await settle(page);
    await press(find());
    await page.settle();
    type(goalBox(), 'Fix the login redirect');
    await page.release('/api/goal/find', json(FOUND));
    await settle(page);
    expect(goalBox().value).toBe('Fix the login redirect');
    expect(mark()).toBeNull();
    expect(note()).toMatch(/left/i);
  });
});
