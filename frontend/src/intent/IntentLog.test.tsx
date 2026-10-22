import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json, mountIntent } from './testing';

const BOARD = {
  generated: 1000,
  annotate: true,
  intent_revision: 'r1',
  sessions: [
    {
      harness: 'claude',
      sid: 'live-1',
      project: 'alpha/app',
      title: 'Alpha work',
      state: 'working',
    },
    { harness: 'codex', sid: 'no-label', project: '', title: 'Unlabelled', state: 'idle' },
  ],
};

const ROWS = [
  {
    harness: 'claude',
    sid: 'live-1',
    goal: 'Ship the queue',
    revision: 2,
    revision_count: 2,
    at: 990,
  },
  {
    harness: 'codex',
    sid: 'no-label',
    goal: 'Tidy the labels',
    revision: 1,
    revision_count: 1,
    at: 980,
  },
  { harness: 'pi', sid: 'gone-1', goal: 'Old words', revision: 1, revision_count: 1, at: 100 },
];

function annotations(rows = ROWS, token = 'r1') {
  return { '/api/annotations': () => json({ annotations: rows, intent_revision: token }) };
}

describe('the Intent log route', () => {
  it('reads the retained rows once on arrival, sends no POST, and holds under StrictMode', async () => {
    const page = mountIntent({ data: BOARD, routes: annotations() });
    await page.settle();
    expect(page.gets('/api/annotations')).toBe(1);
    expect(page.posts()).toBe(0);
    expect(screen.getByText('Typed goal: Ship the queue')).toBeInTheDocument();
    // A poll that brings the same token leaves the rows and asks for nothing.
    await page.poll({ ...BOARD, generated: 1100 });
    expect(page.gets('/api/annotations')).toBe(1);
    expect(page.posts()).toBe(0);
  });

  it('names a /goal as a source and never says no goal is available for a session that holds one', async () => {
    const board = {
      ...BOARD,
      sessions: [
        { ...BOARD.sessions[0], session_goal: { text: 'The findings file exists', at: 900 } },
        BOARD.sessions[1],
      ],
    };
    const page = mountIntent({ data: board, routes: annotations([]) });
    await page.settle();
    expect(
      screen.getByText('Goal stated with /goal: The findings file exists'),
    ).toBeInTheDocument();
    // The other session states none, so its row still says so.
    expect(screen.getAllByText('No goal available from these sources.')).toHaveLength(1);
  });

  it('waits while hidden: a board that arrives on another route fetches no retained words', async () => {
    const page = mountIntent({ hash: '#n=sessions', data: BOARD, routes: annotations() });
    await page.settle();
    await page.poll({ ...BOARD, intent_revision: 'r2' });
    expect(page.gets('/api/annotations')).toBe(0);
    await page.go('#n=intent');
    expect(page.gets('/api/annotations')).toBe(1);
  });

  it('withholds withdrawn words the moment the token moves, and fetches the replacement once', async () => {
    const page = mountIntent({ data: BOARD, routes: annotations() });
    await page.settle();
    expect(screen.getByText('Typed goal: Ship the queue')).toBeInTheDocument();
    page.state.routes['/api/annotations'] = () => 'hold';
    await page.poll({ ...BOARD, intent_revision: 'r2' });
    // The words are gone from the page before the replacement arrives, and the page says why.
    expect(screen.queryByText('Typed goal: Ship the queue')).toBeNull();
    expect(screen.getByText('Reading the annotation store.')).toBeInTheDocument();
    expect(page.gets('/api/annotations')).toBe(2);
    await page.release(
      '/api/annotations',
      json({
        annotations: [{ harness: 'claude', sid: 'live-1', goal: 'New words' }],
        intent_revision: 'r2',
      }),
    );
    expect(screen.getByText('Typed goal: New words')).toBeInTheDocument();
    expect(screen.queryByText('Typed goal: Ship the queue')).toBeNull();
  });

  it('never restores words a stale request carried after the token moved on', async () => {
    const page = mountIntent({ data: BOARD, routes: { '/api/annotations': () => 'hold' } });
    await page.settle();
    await page.poll({ ...BOARD, intent_revision: 'r2' });
    await page.release(
      '/api/annotations',
      json({
        annotations: [{ harness: 'claude', sid: 'live-1', goal: 'Withdrawn' }],
        intent_revision: 'r1',
      }),
    );
    expect(screen.queryByText('Typed goal: Withdrawn')).toBeNull();
    expect(screen.getByText('Reading the annotation store.')).toBeInTheDocument();
  });

  it('says the store could not be read, never an empty log, and retries only after twenty seconds on a redraw', async () => {
    const page = mountIntent({
      data: BOARD,
      routes: { '/api/annotations': () => json({}, 500) },
    });
    await page.settle();
    expect(
      screen.getByText(
        'The annotation store could not be read, so its evidence is unread rather than empty.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('No goal or expected outcome has been saved yet.')).toBeNull();
    await page.poll({ ...BOARD, generated: 1001 });
    expect(page.gets('/api/annotations')).toBe(1);
    await page.advance(20_000);
    await page.poll({ ...BOARD, generated: 1002 });
    expect(page.gets('/api/annotations')).toBe(2);
  });

  it('states annotations off and fetches nothing', async () => {
    const page = mountIntent({ data: { ...BOARD, annotate: false }, routes: annotations() });
    await page.settle();
    expect(page.gets('/api/annotations')).toBe(0);
    expect(
      screen.getByText(
        'Annotations are off for this run. Start without --no-annotations to type a goal and an expected outcome.',
      ),
    ).toBeInTheDocument();
  });

  it('links a session with an empty project label and files it on the board, not as departed', async () => {
    const page = mountIntent({ data: BOARD, routes: annotations() });
    await page.settle();
    const link = screen.getByRole('link', { name: 'Unlabelled' });
    expect(link.getAttribute('href')).toBe('#n=session:' + ':codex:no-label');
    expect(
      screen.getByText('3 sessions listed: 2 on the board, 1 retained after leaving the board.'),
    ).toBeInTheDocument();
    // The departed one is named, and says there is nowhere to open.
    expect(screen.getByText('pi:gone-1')).toBeInTheDocument();
    expect(
      screen.getByText('Not on the board now, so there is nowhere to open. The words are here.'),
    ).toBeInTheDocument();
  });

  it('opens the session through the router, which stamps the Intent log as where it came from', async () => {
    const page = mountIntent({ data: BOARD, routes: annotations() });
    await page.settle();
    fireEvent.click(screen.getByRole('link', { name: 'Alpha work' }));
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({
      view: 'session',
      harness: 'claude',
      session: 'live-1',
      from: 'intent',
    });
  });
});
