import { describe, expect, it } from 'vitest';
import { GENERATED, SIDS, sessionsSearchPayload } from '../../stories/sessionsSearch.fixture';
import { observe, type Row } from '../observed';
import { datedClock } from '../observed/values';
import {
  announcement,
  applyFilters,
  chipText,
  dateChip,
  dateCounts,
  dayEdges,
  EMPTY_FILTERS,
  excerpt,
  facetCounts,
  filtersActive,
  fixedOptions,
  harnessMeta,
  harnessOptions,
  hiddenWaiting,
  indexScreen,
  joinNames,
  narrowOptions,
  normalize,
  prepare,
  projectOptions,
  queryTerms,
  resultLine,
  unstampedHidden,
  unstampedLine,
  waitCoverage,
  type FilterState,
} from './filters';
import { buildSessionsScreen, checkedAgainstCurrentWords, sessionsContext } from './rows';

function board(options: Parameters<typeof sessionsSearchPayload>[0] = {}) {
  const payload = sessionsSearchPayload(options) as Row;
  const screen = buildSessionsScreen(payload, observe(payload));
  return { payload, screen, indexed: indexScreen(screen) };
}

const run = (change: Partial<FilterState>, options: Parameters<typeof board>[0] = {}) => {
  const { indexed, payload } = board(options);
  const generated = (payload['generated'] as number | undefined) ?? null;
  const prepared = prepare({ ...EMPTY_FILTERS, ...change }, generated);
  const filtered = applyFilters(indexed, prepared, (at) => datedClock(at, generated ?? at));
  const sids = indexed
    .filter((one) => filtered.keys.has(one.row.key))
    .map((one) => one.row.session.sid);
  const letter = (sid: string) =>
    Object.entries(SIDS).find(([, value]) => value === sid)?.[0] ?? sid;
  return { indexed, prepared, filtered, letters: sids.map(letter).sort().join('') };
};

describe('the words', () => {
  it('fold case, accents and runs of space, and keep a quoted phrase as one term', () => {
    expect(normalize('  Café\tNOTES ')).toBe('cafe notes');
    expect(queryTerms('release "Combat  Completion" "unclosed')).toEqual([
      'release',
      'combat completion',
      'unclosed',
    ]);
    expect(queryTerms('x'.repeat(250))[0]).toHaveLength(200);
    expect(queryTerms('   ')).toEqual([]);
  });

  it('match what the row shows, and name a prompt it does not show', () => {
    const { letters, filtered, indexed } = run({ query: 'release' });
    expect(letters).toBe('BK');
    const hint = (letter: keyof typeof SIDS) =>
      filtered.hints.get(
        indexed.find((one) => one.row.session.sid === SIDS[letter])?.row.key ?? '',
      );
    expect(hint('B')).toEqual(['Matched in your first prompt: "write the release notes for 2.4"']);
    expect(hint('K')).toBeUndefined();
  });

  it('require every term, each in any field', () => {
    expect(run({ query: 'release codex' }).letters).toBe('K');
    expect(run({ query: 'parser-fix' }).letters).toBe('C');
    expect(run({ query: '"combat completion"' }).letters).toBe('A');
  });

  it('match a session id only by a prefix of six or more id characters', () => {
    const { letters, filtered } = run({ query: SIDS.C.slice(0, 8) });
    expect(letters).toBe('C');
    expect([...filtered.hints.values()][0]).toEqual([`Matched in the session id: "${SIDS.C}"`]);
    expect(run({ query: SIDS.C.slice(0, 5) }).letters).toBe('');
    expect(run({ query: SIDS.C.slice(2, 10) }).letters).toBe('');
  });

  it('never match a placeholder sentence', () => {
    expect(run({ query: 'Add a goal' }).letters).toBe('');
    expect(run({ query: '"Title not published"' }, { showAll: true }).letters).toBe('');
    expect(run({ query: 'Annotations off' }, { annotate: false }).letters).toBe('');
  });

  it('cut a long field to about eighty characters around the match', () => {
    const long = `${'a'.repeat(100)} needle ${'b'.repeat(100)}`;
    const cut = excerpt(long, 'needle');
    expect(cut).toContain('needle');
    expect(cut.startsWith('…')).toBe(true);
    expect(cut.endsWith('…')).toBe(true);
    expect(cut.length).toBeLessThanOrEqual(82);
    expect(excerpt('short', 'short')).toBe('short');
  });
});

describe('the dates', () => {
  it('start each day at local midnight around the board clock, walking calendar days', () => {
    const edges = dayEdges(GENERATED);
    const day = (stamp: number) => new Date(stamp * 1000);
    expect(day(edges.today).getHours()).toBe(0);
    expect(day(edges.today).getDate()).toBe(15);
    expect(day(edges.yesterday).getDate()).toBe(14);
    expect(day(edges.yesterday).getHours()).toBe(0);
    expect(day(edges.week).getDate()).toBe(9);
    expect(edges.hour).toBe(GENERATED - 3600);
  });

  it('keep a day of any length whole across a clock change', () => {
    // 2030-03-11 and 2030-11-04 are a day after US clock changes; whatever the zone, midnight stays midnight.
    for (const at of [new Date(2030, 2, 11, 12), new Date(2030, 10, 4, 12)]) {
      const edges = dayEdges(at.getTime() / 1000);
      expect(new Date(edges.yesterday * 1000).getHours()).toBe(0);
      expect(new Date(edges.yesterday * 1000).getDate()).toBe(at.getDate() - 1);
    }
  });

  it('date a row by its start, or its first message, and never count an unstamped row as old', () => {
    expect(run({ when: 'today' }).letters).toBe('ABEFK');
    expect(run({ when: 'yesterday' }).letters).toBe('CDL');
    expect(run({ when: 'unstamped' }).letters).toBe('GHIJ');
    expect(run({ when: 'today', includeUnstamped: true }).letters).toBe('ABEFGHIJK');
    expect(run({ when: 'week' }).letters).toBe('ABCDEFKL');
    expect(run({ when: 'hour' }).letters).toBe('');
  });

  it('date a row by its last activity in Last active mode', () => {
    expect(run({ dateField: 'active', when: 'yesterday' }).letters).toBe('L');
    expect(run({ dateField: 'active', when: 'today' }).letters).toBe('ABCDEFGHIJK');
  });

  it('counts each choice, the unstamped rows and who publishes no start', () => {
    const { indexed, prepared } = run({ when: 'today' });
    const dates = dateCounts(indexed, prepared);
    expect(Object.fromEntries(dates.byWhen)).toEqual({
      any: 12,
      hour: 0,
      today: 5,
      yesterday: 3,
      week: 8,
      unstamped: 4,
    });
    expect(dates.unstampedHarnesses).toEqual(['Cursor', 'Goose', 'OpenCode', 'Pi']);
    expect(unstampedHidden(dates, prepared)).toBe(4);
    expect(unstampedLine(4, 'started')).toBe(
      '4 sessions have no published start time and are not shown.',
    );
    expect(unstampedLine(1, 'active')).toBe(
      '1 session has no published activity time and is not shown.',
    );
    expect(dateChip(prepared.filters, dates.unstamped)).toBe('Started: Today');
    expect(dateChip({ ...prepared.filters, includeUnstamped: true }, 4)).toBe(
      'Started: Today, plus 4 with no start time',
    );
  });

  it('hint the time that dated a row while a date choice is on', () => {
    const { filtered, indexed } = run({ when: 'week' });
    const c = indexed.find((one) => one.row.session.sid === SIDS.C);
    expect(filtered.hints.get(c?.row.key ?? '')).toEqual([
      'Started 2030-01-14 16:02, from the first message',
    ]);
  });

  it('filter nothing by date when the board published no clock', () => {
    const { indexed } = board();
    const prepared = prepare({ ...EMPTY_FILTERS, when: 'today' }, null);
    expect(applyFilters(indexed, prepared, String).shown).toBe(12);
  });
});

describe('the facets', () => {
  it('list projects in collator order with the empty label last, and a shared location only by key', () => {
    const { indexed, prepared } = run({});
    const options = projectOptions(indexed, prepared);
    expect(options.map((one) => `${one.label} ${String(one.count)}`)).toEqual([
      'compass 2',
      'projects/pendulum-of-despair 2',
      'recce-cloud-infra 1',
      'recce/compass 6',
      'No project published 1',
    ]);
    expect(options.find((one) => one.value === 'compass')?.note).toBe(
      'Label shared by more than one location',
    );
    expect(options.find((one) => one.value === 'recce/compass')?.note).toBe('');
  });

  it('keep a chosen project the board no longer holds', () => {
    const { indexed, prepared } = run({ project: ['gone'] });
    const gone = projectOptions(indexed, prepared).at(-1);
    expect(gone).toMatchObject({ value: 'gone', count: null, note: 'Not on the board now' });
  });

  it('OR within a facet and AND across facets, with faceted counts', () => {
    const { letters, indexed, prepared } = run({ project: ['compass', 'recce/compass'] });
    expect(letters).toBe('BCDEFGHK');
    const state = Object.fromEntries(facetCounts(indexed, prepared, 'state'));
    expect(state).toEqual({ Working: 2, Idle: 5, Ended: 1 });
    // The project counts ignore the project choice itself.
    expect(projectOptions(indexed, prepared).map((one) => one.count)).toEqual([2, 2, 1, 6, 1]);
    expect(run({ project: ['recce/compass'], state: ['Working'] }).letters).toBe('BC');
  });

  it('list only discovered harnesses, and an unreadable store without a count', () => {
    const { indexed, prepared, payload } = { ...run({}), payload: sessionsSearchPayload() };
    const options = harnessOptions(indexed, prepared, harnessMeta(payload as Row));
    expect(options.map((one) => one.label)).toEqual([
      'Claude Code',
      'Codex',
      'Gemini',
      'Cursor',
      'Pi',
      'Goose',
      'OpenCode',
      'Droid',
    ]);
    expect(options.at(-1)).toMatchObject({
      count: null,
      disabled: true,
      note: 'Store could not be read',
    });
    expect(options[0]?.count).toBe(5);
  });

  it('partition state, drift and goal so each sums to the board', () => {
    const { indexed, prepared } = run({});
    const counts = (facet: 'state' | 'drift' | 'goal') =>
      fixedOptions(indexed, prepared, facet).map((one) => one.count);
    expect(counts('state')).toEqual([1, 2, 7, 1, 1]);
    expect(counts('drift')).toEqual([1, 1, 10]);
    expect(counts('goal')).toEqual([2, 0, 10]);
    expect(run({ drift: ['recorded'] }).letters).toBe('D');
    expect(run({ drift: ['checked'] }).letters).toBe('K');
    expect(run({ goal: ['saved'] }).letters).toBe('BK');
  });

  it('filter nothing on drift or goal while annotations are off', () => {
    const { indexed, prepared } = run({}, { annotate: false });
    expect(indexed.every((one) => one.drift === null && one.goal === null)).toBe(true);
    expect(run({ drift: ['recorded'], goal: ['saved'] }, { annotate: false }).letters).toHaveLength(
      12,
    );
    expect(fixedOptions(indexed, prepared, 'drift').map((one) => one.count)).toEqual([0, 0, 0]);
  });

  it('narrow a long project list without choosing', () => {
    const { indexed, prepared } = run({});
    expect(
      narrowOptions(projectOptions(indexed, prepared), 'recce').map((one) => one.value),
    ).toEqual(['recce-cloud-infra', 'recce/compass']);
  });
});

describe('the guards and sentences', () => {
  it('name a waiting session the filters hide', () => {
    const { indexed, filtered } = run({ project: ['recce-cloud-infra'] });
    expect(hiddenWaiting(indexed, filtered).map((one) => one.row.session.sid)).toEqual([SIDS.A]);
    expect(hiddenWaiting(indexed, run({}).filtered)).toEqual([]);
  });

  it('say which harnesses cannot report a wait, and which only in some setups', () => {
    const { indexed } = run({});
    expect(waitCoverage(indexed, harnessMeta(sessionsSearchPayload() as Row))).toEqual([
      'Gemini and Goose do not report when a session is waiting, so 2 of their sessions could be waiting without showing here.',
      "Codex, OpenCode and Pi report a wait only in some setups; Attention's coverage says which.",
    ]);
  });

  it('count the whole board while filtering, and speak the reader’s change', () => {
    const all = run({}).filtered;
    expect(filtersActive(EMPTY_FILTERS)).toBe(false);
    expect(resultLine(all, { showAll: false, hours: 24 })).toBe(
      '12 sessions active in the last 24 hours.',
    );
    expect(resultLine(all, { showAll: true, hours: 24 })).toBe('12 stored sessions.');
    expect(resultLine(all, { showAll: false, hours: null })).toBe('12 sessions on this board.');
    const some = run({ query: 'release' }).filtered;
    expect(resultLine(some, { showAll: false, hours: 24 })).toBe(
      'Showing 2 of 12 sessions. ACTIVE NOW and WORKING above count the whole board.',
    );
    expect(announcement(some)).toBe('Showing 2 of 12 sessions.');
    expect(announcement(run({ query: 'zzzz' }).filtered)).toBe('No session matches these filters.');
    expect(announcement(all)).toBe('Filters cleared. Showing all 12 sessions.');
  });

  it('shorten a long chip and join names in plain English', () => {
    expect(chipText('Project', ['compass', 'recce/compass']).short).toBe(
      'Project: compass, recce/compass',
    );
    expect(
      chipText('Project', ['recce/compass', 'projects/pendulum-of-despair', 'recce-cloud-infra'])
        .short,
    ).toBe('Project: recce/compass +2 more');
    expect(joinNames(['A'])).toBe('A');
    expect(joinNames(['A', 'B'])).toBe('A and B');
    expect(joinNames(['A', 'B', 'C'])).toBe('A, B and C');
  });
});

describe('checked against the current words', () => {
  const on = sessionsContext({ annotate: true });
  it('is null with annotations off, and a reading of earlier words is not one', () => {
    expect(checkedAgainstCurrentWords({}, sessionsContext({}))).toBeNull();
    expect(checkedAgainstCurrentWords(undefined, on)).toBe(false);
    expect(checkedAgainstCurrentWords({ departure_checked: true }, on)).toBe(true);
    expect(
      checkedAgainstCurrentWords(
        { annotation_assessment: { revision_read: 1 }, annotation_revision: 2 },
        on,
      ),
    ).toBe(false);
    expect(
      checkedAgainstCurrentWords(
        { annotation_assessment: { revision_read: 2 }, annotation_revision: 2 },
        on,
      ),
    ).toBe(true);
  });
});
