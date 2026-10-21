import { describe, expect, it } from 'vitest';
import { delegatedWork, observe, pageTitleOf, readHint, sessionStop } from './index';

/* What the model says, written out, so the differential test against the legacy file is not the only
   oracle: the rules a reader depends on, each with the payload that proves it. */

const NOW = 10_000;
const board = (sessions: unknown[], extra: Record<string, unknown> = {}) => ({
  generated: NOW,
  sessions,
  ...extra,
});

describe('identity is the harness and the sid together', () => {
  it('keeps one sid under two harnesses as two sessions and attributes a request to the pair it names', () => {
    const model = observe(
      board(
        [
          { harness: 'claude', sid: 'shared', project: 'p', state: 'idle' },
          { harness: 'codex', sid: 'shared', project: 'p', state: 'idle' },
        ],
        {
          ask: true,
          asks: [{ id: 'a', harness: 'codex', session_id: 'shared', question: 'Approve?' }],
        },
      ),
    );
    expect(model.sessions.map((row) => [row.harness, row.askKnown])).toEqual([
      ['claude', false],
      ['codex', true],
    ]);
  });

  it('attributes a request that names no harness to nobody when two harnesses carry the sid, and says so on the board', () => {
    const model = observe(
      board(
        [
          { harness: 'claude', sid: 'shared', project: 'p' },
          { harness: 'codex', sid: 'shared', project: 'p' },
        ],
        { ask: true, asks: [{ id: 'a', session_id: 'shared', question: 'Approve?' }] },
      ),
    );
    expect(model.sessions.every((row) => !row.askKnown)).toBe(true);
    expect(model.boardRisks.map((risk) => [risk.kind, risk.title])).toContainEqual([
      'ask',
      'Exact request without an identified session',
    ]);
  });

  it('keeps a sid with colons and a missing harness exactly as published', () => {
    const model = observe(
      board([
        { sid: 'a:b:c', project: 'p' },
        { harness: 'claude', sid: 'a:b:c', project: 'p' },
      ]),
    );
    expect(model.sessions.map((row) => [row.harness, row.sid])).toEqual([
      ['', 'a:b:c'],
      ['claude', 'a:b:c'],
    ]);
  });
});

describe('an end is only what was observed', () => {
  it('retires the state word on a session with an end stamp, and leaves a session without one in the state it published', () => {
    const model = observe(
      board([
        {
          harness: 'claude',
          sid: 'ended',
          project: 'p',
          state: 'working',
          active: true,
          ended_at: NOW - 60,
        },
        { harness: 'claude', sid: 'silent', project: 'p', state: 'working', active: true },
      ]),
    );
    const [ended, silent] = model.sessions;
    expect(ended).toMatchObject({
      isEnded: true,
      isWorking: false,
      isLive: false,
      isActive: false,
    });
    expect(silent).toMatchObject({ isEnded: false, isWorking: true, isLive: true, isActive: true });
    expect(ended?.landing.endKind).toBe('session-end');
    expect(silent?.landing.endKind).toBe('running');
  });

  it('does not read a zero, negative or non-numeric end stamp as an end', () => {
    const model = observe(
      board([
        { harness: 'a', sid: '1', ended_at: 0 },
        { harness: 'a', sid: '2', ended_at: -4 },
        { harness: 'a', sid: '3', ended_at: '5' },
      ]),
    );
    expect(model.sessions.map((row) => row.isEnded)).toEqual([false, false, false]);
  });

  it('keeps a held request active on an ended session, because the request has a lifecycle of its own', () => {
    const model = observe(
      board([{ harness: 'claude', sid: 's', project: 'p', state: 'idle', ended_at: NOW - 5 }], {
        ask: true,
        asks: [{ id: 'a', harness: 'claude', session_id: 's', question: 'Still there?' }],
      }),
    );
    expect(model.sessions[0]).toMatchObject({
      isEnded: true,
      askKnown: true,
      isActive: true,
      isNeeds: false,
    });
  });

  it('names the three ways an idle session is silent apart, and never a completion nobody observed', () => {
    const model = observe(
      board([
        { harness: 'claude', sid: 'stopped', state: 'idle', finished_at: NOW - 30 },
        { harness: 'claude', sid: 'plain', state: 'idle' },
        { harness: 'claude', sid: 'scan', state: 'idle', acquisition: 'scan-only' },
      ]),
    );
    expect(model.sessions.map((row) => row.landing.endKind)).toEqual([
      'turn-stop',
      'idle-unknown',
      'unobservable',
    ]);
    expect(model.sessions[1]?.landing).toMatchObject({
      endKnown: false,
      endText: 'Idle with completion unknown: no stop and no end was observed',
      claimKind: 'none',
      claimText: 'Nothing has claimed this session finished',
    });
    // Nothing corroborates the agent's own account, and the model says why instead of leaving a blank.
    expect(model.sessions[1]?.landing.independentKnown).toBe(false);
    expect(model.sessions[1]?.landing.independentText).toContain('Git state was not measured');
  });
});

describe('a fact that was not measured says why, and never reads as a figure', () => {
  const [row] = observe(
    board([{ harness: 'cursor', sid: 's', project: 'p', state: 'working' }]),
  ).sessions;

  it('words every absence', () => {
    expect(row).toMatchObject({
      titleText: 'Title not published',
      titleKnown: false,
      rateText: 'Token rate not reported',
      rateKnown: false,
      waitedText: 'Wait duration not published',
      waitedKnown: false,
      whereText: 'Exact location not published',
      nextText: 'No pending step published',
      gitText: 'Git state was not measured',
      outcomeText: 'No stop or end observed',
      stuckText: 'No stuck signal published',
      askText: 'No exact request published',
      ownGoalText: 'This session published no goal',
    });
    expect(row?.blockText).toBe('Harness does not report blocks');
  });

  it('counts a rate only when the harness reports one and no source gap says otherwise', () => {
    const payload = (gaps: unknown[]) =>
      board([{ harness: 'claude', sid: 's', rate_per_min: 1234.4, source_gaps: gaps }], {
        harnesses: [{ key: 'claude', reports_rate: true, reports_needs_input: true }],
      });
    expect(observe(payload([])).sessions[0]).toMatchObject({
      rateKnown: true,
      rateText: '1,234 /m',
    });
    expect(observe(payload(['token accounting'])).sessions[0]).toMatchObject({ rateKnown: false });
    expect(observe(payload(['block state'])).sessions[0]).toMatchObject({
      blockText: 'Block state could not be read',
    });
  });

  it('tells a harness that reports no blocks apart from one that reports none', () => {
    const none = observe(
      board([{ harness: 'claude', sid: 's', state: 'idle' }], {
        harnesses: [{ key: 'claude', reports_needs_input: true }],
      }),
    );
    expect(none.sessions[0]).toMatchObject({ blockText: 'No reported block', blockKnown: true });
    const unreadable = observe(
      board([{ harness: 'claude', sid: 's', state: 'idle' }], {
        harnesses: [{ key: 'claude', error: 'x', reports_needs_input: true }],
      }),
    );
    expect(unreadable.sessions[0]).toMatchObject({
      blockText: 'Harness does not report blocks',
      blockKnown: false,
    });
  });
});

describe('the counts are read from the rows the page renders', () => {
  const model = observe(
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
      { harness: 'claude', sid: 'c', project: 'q', state: 'idle', ended_at: 5 },
      { harness: 'claude', sid: 'd', project: 'q', state: 'idle' },
    ]),
  );

  it('derives every total from the session list', () => {
    expect(model.totals).toMatchObject({
      sessions: 4,
      running: 1,
      needs: 1,
      ended: 1,
      quiet: 1,
      subagents: 2,
    });
    expect(model.counters.map((counter) => [counter.label, counter.value])).toEqual([
      ['ACTIVE NOW', 2],
      ['WORKING', 1],
      ['EXACT REQUESTS', 0],
      ['REPORTED BLOCKS', 1],
    ]);
  });

  it('orders the active lane gate-first and the history lane by nearest activity, then sid', () => {
    const lanes = observe(
      board([
        { harness: 'h', sid: 'w2', state: 'working', last_activity: 1 },
        { harness: 'h', sid: 'g', state: 'needs_input' },
        { harness: 'h', sid: 'w1', state: 'working', last_activity: 1 },
        { harness: 'h', sid: 'old', state: 'idle', last_activity: 5 },
        { harness: 'h', sid: 'new', state: 'idle', last_activity: 9 },
      ]),
    );
    expect(lanes.active.map((row) => row.sid)).toEqual(['g', 'w1', 'w2']);
    expect(lanes.history.map((row) => row.sid)).toEqual(['new', 'old']);
  });

  it('ranks projects needs-first and states a shared label as a collision, but not for a blank label', () => {
    const grouped = observe(
      board([
        { harness: 'h', sid: '1', project: 'same', state: 'idle' },
        { harness: 'h', sid: '2', project: 'same', state: 'idle' },
        { harness: 'h', sid: '3', project: '', state: 'idle' },
        { harness: 'h', sid: '4', project: '', state: 'idle' },
        { harness: 'h', sid: '5', project: 'needy', state: 'needs_input' },
      ]),
    );
    expect(grouped.projects.map((project) => project.key)).toEqual(['needy', '', 'same']);
    expect(
      grouped.boardRisks.filter((risk) => risk.kind === 'collision').map((risk) => risk.identity),
    ).toEqual(['same display label']);
    expect(grouped.sessions[0]?.sharedLabelText).toBe(
      '2 sessions share this display label; shared location is not established',
    );
  });
});

describe('delegated work states what it cannot see', () => {
  it('says not measured when the counts are not integers', () => {
    expect(delegatedWork({ delegated_launches: null }, NOW)).toEqual({
      draw: false,
      risky: false,
      text: 'Delegated work: not measured; Compass cannot see work this session started.',
    });
    expect(delegatedWork({ delegated_launches: 2, delegated_unpaired: -1 }, NOW).text).toContain(
      'not measured',
    );
  });

  it('draws only where a launch was recorded, and is risky only after half an hour of silence with an unpaired launch', () => {
    const row = { delegated_launches: 1, delegated_unpaired: 1, delegated_visibility: 'partial' };
    const quiet = delegatedWork({ ...row, delegated_quiet_since: NOW - 1800 }, NOW);
    expect(quiet).toMatchObject({ draw: true, risky: true });
    expect(quiet.text).toContain('Nothing recorded for 30 minutes.');
    expect(quiet.text).toContain('Compass cannot see all work this session started.');
    expect(delegatedWork({ ...row, delegated_quiet_since: NOW - 1799 }, NOW).risky).toBe(false);
    expect(
      delegatedWork({ ...row, delegated_unpaired: 0, delegated_quiet_since: NOW - 9000 }, NOW)
        .risky,
    ).toBe(false);
    expect(delegatedWork({ ...row, delegated_launches: 0, delegated_unpaired: 0 }, NOW).draw).toBe(
      false,
    );
  });
});

describe('a turn stop is the hook’s, or the transcript’s named as the transcript’s', () => {
  it('prefers the hook, and reads the transcript stop only for a harness that records one', () => {
    expect(sessionStop({ harness: 'claude', finished_at: 5, turn_end_at: 9 })).toEqual({
      at: 5,
      kind: 'hook',
    });
    expect(sessionStop({ harness: 'claude', turn_end_at: 9 })).toEqual({
      at: 9,
      kind: 'transcript',
    });
    expect(sessionStop({ harness: 'codex', turn_end_at: 9 })).toBeNull();
  });

  it('says what an analysis will read before the press, and nothing where the server would refuse', () => {
    expect(readHint({ harness: 'claude', state: 'working' })).toBe(
      'Reads the work so far; the session is still running.',
    );
    expect(readHint({ harness: 'claude', state: 'idle', ended_at: 4 })).toBe(
      'Reads the session up to its end against your intent.',
    );
    expect(readHint({ harness: 'claude', state: 'idle', finished_at: 4 })).toBe(
      'Reads the session up to its last turn against your intent.',
    );
    expect(readHint({ harness: 'codex', state: 'idle', finished_at: 4 })).toBe('');
  });

  it('says an idle Claude Code session with no recorded finish is read up to its last entry', () => {
    const line =
      'Reads the session up to its last recorded entry; its last turn was not recorded as finished.';
    expect(readHint({ harness: 'claude', state: 'idle' })).toBe(line);
    expect(readHint({ harness: 'claude', state: 'idle', acquisition: 'scan-only' })).toBe(line);
    // Another harness is still withheld there, so it is told nothing about what would be read.
    expect(readHint({ harness: 'codex', state: 'idle' })).toBe('');
  });
});

describe('an unreadable payload is an empty model, never an exception', () => {
  it.each([null, undefined, [], 'x', 7, {}, { sessions: 'x' }, { sessions: [null, 3, 'x', []] }])(
    '%j',
    (payload) => {
      const model = observe(payload);
      expect(model.sessions).toEqual([]);
      expect(model.totals.sessions).toBe(0);
      // Zero rows is a measured zero here, and the caller distinguishes an absent collection itself.
      expect(model.coverage.observed).toContain('0 of 0 sessions carry a subject');
    },
  );
});

describe('the session heading stands in for an identifier-only title', () => {
  const row = (extra: Record<string, unknown>) => ({
    harness: 'claude',
    sid: 'abc12345',
    title: 'DRC-4929',
    ...extra,
  });
  it('prefers the first prompt to the last one', () => {
    expect(
      pageTitleOf(
        row({
          first_prompt: 'Fix the flaky http test',
          first_prompt_at: 1,
          last_prompt: 'ok go on',
        }),
      ),
    ).toBe('Fix the flaky http test');
  });
  it('skips a copied first prompt', () => {
    expect(
      pageTitleOf(
        row({
          first_prompt: 'copied words',
          copied_prompts: [{ quoted_as: ['first_prompt'] }],
          last_prompt: 'later words',
        }),
      ),
    ).toBe('later words');
  });
  it('skips a control first prompt', () => {
    expect(
      pageTitleOf(
        row({ first_prompt: '/clear', first_prompt_control: true, last_prompt: 'later words' }),
      ),
    ).toBe('later words');
  });
  it('replaces a UUID title and a title equal to the sid', () => {
    expect(
      pageTitleOf(
        row({ title: '3f2b8c1e-1111-4222-8333-444455556666', first_prompt: 'Real words' }),
      ),
    ).toBe('Real words');
    expect(pageTitleOf(row({ title: 'abc12345', first_prompt: 'Real words' }))).toBe('Real words');
  });
  it('keeps a real title and cuts a long line at 120 characters', () => {
    expect(pageTitleOf(row({ title: 'Ship the redesign', first_prompt: 'x' }))).toBe(
      'Ship the redesign',
    );
    const long = pageTitleOf(row({ first_prompt: 'a'.repeat(200) }));
    expect(long).toHaveLength(120);
    expect(long.endsWith('…')).toBe(true);
  });
});
