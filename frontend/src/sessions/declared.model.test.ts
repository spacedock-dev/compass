// @vitest-environment node
import { describe, expect, it } from 'vitest';
import fixture from '../../test/fixtures/declared-sessions.json';
import { observe, type Row } from '../observed';
import { declaredRelations, groupLabel, nestRows } from './declared';
import { buildSessionsScreen } from './rows';
import {
  applyFilters,
  EMPTY_FILTERS,
  facetCounts,
  groupOptions,
  indexScreen,
  prepare,
} from './filters';

const payload = fixture.payload as Row;
const screen = buildSessionsScreen(payload, observe(payload));
const indexed = indexScreen(screen);

describe('the declared-session model', () => {
  it('never infers a parent from matching labels or an unmatched declaration', () => {
    expect(declaredRelations(payload, fixture.payload.sessions[1]).parent).toBeNull();
    expect(
      declaredRelations(payload, { declared_parent: { harness: 'claude', sid: 'parent' } }).parent,
    ).toBeNull();
    expect(declaredRelations({ sessions: [] }, fixture.payload.sessions[0]).parentText).toContain(
      'not linked',
    );
  });
  it('names an untitled child by its sid and a missing waiting child as absent', () => {
    const source = fixture.payload.sessions[2] ?? {};
    expect(
      declaredRelations({ sessions: [{ ...fixture.payload.sessions[0], title: '' }] }, source)
        .waitingText,
    ).toBe('Waiting on child "child"');
    expect(declaredRelations({ sessions: [] }, source).waitingText).toBe(
      'Waiting on child not on the board',
    );
  });
  it('places only visible children after visible parents', () => {
    expect(nestRows(screen.active).map((one) => [one.row.session.sid, one.depth])).toEqual([
      ['parent', 0],
      ['child', 1],
    ]);
    expect(
      nestRows(screen.active.filter((row) => row.session.sid === 'child')).map((one) => one.depth),
    ).toEqual([0]);
  });
});

describe('the Group facet', () => {
  it('counts groups with its own choice left out and combines with Headless', () => {
    const prepared = prepare(
      {
        ...EMPTY_FILTERS,
        group: [fixture.payload.sessions[0]?.group ?? ''],
        headless: ['headless'],
      },
      1900000000,
      true,
    );
    expect(applyFilters(indexed, prepared, () => '').shown).toBe(1);
    expect([...facetCounts(indexed, prepared, 'group').values()]).toEqual([1]);
  });
  it('keeps an absent chosen group so a reader can clear it', () => {
    const options = groupOptions(
      indexed,
      prepare({ ...EMPTY_FILTERS, group: ['gone'] }, null, true),
    );
    expect(options.find((one) => one.value === 'gone')).toMatchObject({
      label: '"gone"',
      count: null,
      note: 'Not on the board now',
    });
  });
  it('offers No group without drawing an empty label and preserves a capped unusual group', () => {
    const bare = { harness: 'codex', sid: 'bare', project: 'demo', state: 'idle' };
    const more = { ...payload, sessions: [...fixture.payload.sessions, bare] };
    const rows = indexScreen(buildSessionsScreen(more, observe(more)));
    const prepared = prepare({ ...EMPTY_FILTERS, group: [''] }, null, true);
    expect(applyFilters(rows, prepared, () => '').shown).toBe(1);
    expect(groupOptions(rows, prepared).find((one) => one.value === '')?.label).toBe('No group');
    expect(groupLabel(bare)).toBe('');
    expect([...(fixture.payload.sessions[1]?.group ?? '')]).toHaveLength(40);
    expect(groupLabel(fixture.payload.sessions[1])).toContain('<&> "é"');
  });
});

it('a literal No group name stays distinct from the absence in Group choices', () => {
  const data = {
    ...payload,
    sessions: [
      { harness: 'codex', sid: 'literal', project: 'demo', state: 'idle', group: 'No group' },
      { harness: 'codex', sid: 'absent', project: 'demo', state: 'idle' },
    ],
  };
  const rows = indexScreen(buildSessionsScreen(data, observe(data)));
  const options = groupOptions(rows, prepare(EMPTY_FILTERS, null, true));
  expect(options.find((one) => one.value === 'No group')?.label).toBe('"No group"');
  expect(options.find((one) => one.value === '')?.label).toBe('No group');
  expect(new Set(options.map((one) => one.label)).size).toBe(2);
});

it('a reader can find a group-only word without admitting an unrelated row', () => {
  const data = {
    ...payload,
    sessions: [
      {
        harness: 'codex',
        sid: 'chosen',
        project: 'demo',
        title: 'Build',
        state: 'idle',
        group: 'orchard',
      },
      {
        harness: 'codex',
        sid: 'other',
        project: 'demo',
        title: 'Check',
        state: 'idle',
        group: 'grove',
      },
    ],
  };
  const rows = indexScreen(buildSessionsScreen(data, observe(data)));
  const result = applyFilters(
    rows,
    prepare({ ...EMPTY_FILTERS, query: 'orchard' }, null, true),
    () => '',
  );
  expect(
    rows.filter((one) => result.keys.has(one.row.key)).map((one) => one.row.session.sid),
  ).toEqual(['chosen']);
});
