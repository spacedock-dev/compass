import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GENERATED, SIDS, sessionsSearchPayload } from '../../stories/sessionsSearch.fixture';
import type { Row } from '../observed';
import { mountSessions } from './testing';

/* The toolbar in jsdom, so the coverage gate measures what the sign-off stories prove in Chromium. The board
   is the stories' twelve-row fixture; its derived totals are listed at the top of that file. */

type Page = ReturnType<typeof mountSessions>;

async function open(data: Row = sessionsSearchPayload() as Row) {
  const page = mountSessions({ data });
  await page.settle();
  return page;
}

const result = () => document.querySelector('[data-sessions-result]')?.textContent ?? '';
const cue = () => document.querySelector('#next-cockpit-cue-status')?.textContent ?? '';
const chips = () =>
  [...document.querySelectorAll('[data-sessions-chip]')].map((one) => one.textContent);
const rows = () => document.querySelectorAll('article.next-operation-row').length;
const field = () => screen.getByRole('searchbox', { name: 'Search sessions' }) as HTMLInputElement;
const preset = (name: string) => screen.getByRole('button', { name });
const tab = (name: string) =>
  within(screen.getByRole('group', { name: 'Session status' })).getByRole('button', {
    name: new RegExp(`^${name} [0-9]+$`),
  });

async function press(page: Page, node: Element) {
  fireEvent.click(node);
  await page.settle();
}

async function openPanel(page: Page) {
  const button = preset('Filters');
  if (button.getAttribute('aria-expanded') !== 'true') await press(page, button);
  return screen.getByRole('region', { name: 'Filters' });
}

async function openFilter(page: Page, facet: string) {
  const panel = await openPanel(page);
  const more = within(panel).getByRole('button', { name: 'More filters for power users' });
  if (more.getAttribute('aria-expanded') !== 'true') await press(page, more);
  const section = panel.querySelector<HTMLElement>(`[data-filter-facet="${facet}"]`);
  if (!section) throw new Error(`Missing ${facet} facet`);
  return section;
}

async function startedToday(page: Page) {
  const panel = await openPanel(page);
  return within(within(panel).getByRole('group', { name: 'Started' })).getByRole('button', {
    name: 'Today',
  });
}

async function pick(page: Page, popup: HTMLElement, label: string) {
  await press(
    page,
    within(popup).getByText(label, {
      exact: true,
      selector: '[data-filter-label], [data-filter-option^="date-field:"] span:last-child',
    }),
  );
}

async function type(page: Page, text: string) {
  const node = field();
  node.value = text;
  fireEvent.input(node);
  await page.settle();
}

async function closeFilters(page: Page) {
  const button = preset('Filters');
  if (button.getAttribute('aria-expanded') === 'true') await press(page, button);
}

const nothing = () => document.querySelector('[data-sessions-nothing]');

describe('tabs and filter choices', () => {
  it('keeps a reader’s headless choice across a poll and clears it with the other filters', async () => {
    const page = await open();
    const popup = await openFilter(page, 'headless');
    expect(
      within(popup).getByText(
        'Read from Claude Code transcripts and Codex rollout metadata. Interactive or unknown includes unknown entrypoints and other harnesses.',
      ),
    ).toBeVisible();
    await pick(page, popup, 'Interactive or unknown');
    await closeFilters(page);
    expect(rows()).toBe(11);
    expect(document.querySelector(`[data-next-session="${SIDS.B}"]`)).toBeNull();
    expect(document.querySelector(`[data-next-session="${SIDS.A}"]`)).not.toBeNull();
    expect(document.querySelector(`[data-next-session="${SIDS.C}"]`)).not.toBeNull();
    expect(chips()).toEqual(['Headless: Interactive or unknown']);
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1 }));
    expect(rows()).toBe(11);
    await press(page, preset('Clear all'));
    expect(rows()).toBe(12);
    const headlessPopup = await openFilter(page, 'headless');
    await pick(page, headlessPopup, 'Headless');
    await closeFilters(page);
    expect(rows()).toBe(1);
    expect(document.querySelector(`[data-next-session="${SIDS.B}"]`)).not.toBeNull();
    expect(document.querySelector(`[data-next-session="${SIDS.A}"]`)).toBeNull();
    expect(document.querySelector(`[data-next-session="${SIDS.C}"]`)).toBeNull();
    expect(chips()).toEqual(['Headless: Headless']);
  });

  it('combines a status tab and a date chip, and clears the date independently', async () => {
    const page = await open();
    await press(page, tab('Waiting on you'));
    expect(tab('Waiting on you').getAttribute('aria-pressed')).toBe('true');
    expect(chips()).toEqual(['Waiting on you']);
    expect(rows()).toBe(1);
    await press(page, await startedToday(page));
    expect(chips()).toEqual(['Waiting on you', 'Started: Today']);
    await press(page, preset('Remove Started: Today'));
    expect(chips()).toEqual(['Waiting on you']);
    expect(rows()).toBe(1);
    await press(page, tab('All'));
    expect(rows()).toBe(12);
  });

  it('clears everything at once and returns the reader to the field', async () => {
    const page = await open();
    await type(page, 'release');
    await press(page, tab('Waiting on you'));
    expect(nothing()?.textContent).toContain('Nothing here matches.');
    await press(page, screen.getByRole('button', { name: 'Clear all' }));
    expect(field().value).toBe('');
    expect(chips()).toEqual([]);
    expect(rows()).toBe(12);
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
  });

  it('toggles an advanced state alongside an agent chip', async () => {
    const page = await open();
    const state = await openFilter(page, 'state');
    await pick(page, state, 'Working');
    expect(rows()).toBe(2);
    const agents = within(await openPanel(page)).getByRole('group', { name: 'Agent' });
    await press(page, within(agents).getByRole('button', { name: /^Codex / }));
    expect(chips()).toEqual(['Agent: Codex', 'State: Working']);
    expect(rows()).toBe(1);
  });
});

describe('what the cue region says', () => {
  it('speaks a press at once and typing only after the reader pauses', async () => {
    const page = await open();
    await press(page, tab('Waiting on you'));
    expect(cue()).toBe('Showing 1 of 12 sessions.');
    // The same count after a second press is spoken again: a fresh write, not the old node.
    const before = document.querySelector('#next-cockpit-cue-status')?.firstChild;
    const project = await openFilter(page, 'project');
    await pick(page, project, 'projects/pendulum-of-despair');
    expect(cue()).toBe('Showing 1 of 12 sessions.');
    expect(document.querySelector('#next-cockpit-cue-status')?.firstChild).not.toBe(before);
    await press(page, screen.getByRole('button', { name: 'Clear all' }));
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
    await type(page, 'rel');
    act(() => page.clock.advance(599));
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
    act(() => page.clock.advance(1));
    expect(cue()).toBe('Showing 2 of 12 sessions.');
  });

  it('says nothing when a poll re-filters the board', async () => {
    const page = await open();
    await press(page, tab('Waiting on you'));
    const said = document.querySelector('#next-cockpit-cue-status')?.firstChild;
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1 }));
    expect(document.querySelector('#next-cockpit-cue-status')?.firstChild).toBe(said);
  });
});

describe('choices the board cannot apply', () => {
  it('disables Today and claims no date filter when the board published no clock', async () => {
    const { generated: _clock, ...payload } = sessionsSearchPayload();
    const page = await open(payload);
    expect(((await startedToday(page)) as HTMLButtonElement).disabled).toBe(true);
    const panel = await openPanel(page);
    expect(panel.textContent).toContain(
      'The board published no clock time, so dates cannot be filtered.',
    );
    expect(result()).not.toContain('Showing');
  });

  it('keeps a date chip after the board stops publishing a clock, and says why it filters nothing', async () => {
    const page = await open();
    await press(page, await startedToday(page));
    expect(rows()).toBe(5);
    await closeFilters(page);
    const { generated: _clock, ...payload } = sessionsSearchPayload();
    await page.poll(payload);
    expect(chips()).toEqual(['Started: Today']);
    const note = document.querySelector('[data-sessions-chip-note]');
    expect(note?.textContent).toBe(
      'The board published no clock time, so dates cannot be filtered. The Date chip filters nothing.',
    );
    expect(document.querySelector('[data-sessions-chip]')?.getAttribute('aria-describedby')).toBe(
      note?.id,
    );
    expect(result()).not.toContain('Showing');
    expect(rows()).toBe(12);
  });

  it('withholds progress records and goal sources while the annotation store cannot be read', async () => {
    const page = await open();
    await press(
      page,
      within(await openFilter(page, 'drift')).getByRole('checkbox', { name: 'Drift recorded' }),
    );
    await closeFilters(page);
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1, unreadable: true }));
    expect(screen.queryByRole('button', { name: 'Drift recorded' })).toBeNull();
    expect(chips()).toEqual(['Progress records: Drift recorded']);
    expect(document.querySelector('[data-sessions-chip-note]')?.textContent).toBe(
      'The annotation store could not be read, so progress and goals cannot be filtered. The Progress records chip filters nothing.',
    );
    expect(rows()).toBe(12);
    for (const facet of ['drift', 'goal'] as const) {
      const popup = await openFilter(page, facet);
      expect(popup.querySelector('[data-sessions-annotations-off]')?.textContent).toBe(
        'The annotation store could not be read, so progress and goals cannot be filtered.',
      );
      expect(popup.querySelector('[data-filter-option]')).toBeNull();
      await closeFilters(page);
    }
    await press(
      page,
      screen.getByRole('button', { name: 'Remove Progress records: Drift recorded' }),
    );
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
  });

  it('never says filters were cleared for a setting changed while nothing is chosen', async () => {
    const page = await open();
    const date = await openFilter(page, 'date');
    await press(page, within(date).getByRole('radio', { name: 'Last active' }));
    expect(cue()).toBe('Showing all 12 sessions.');
  });

  it('keeps a progress records chip after annotations go off, says why it filters nothing, and claims no filter', async () => {
    const page = await open();
    await press(
      page,
      within(await openFilter(page, 'drift')).getByRole('checkbox', { name: 'Drift recorded' }),
    );
    expect(rows()).toBe(1);
    await closeFilters(page);
    await page.poll(sessionsSearchPayload({ annotate: false }));
    expect(chips()).toEqual(['Progress records: Drift recorded']);
    const note = document.querySelector('[data-sessions-chip-note]');
    expect(note?.textContent).toBe(
      'Progress records are not published because annotations are off. The Progress records chip filters nothing.',
    );
    expect(document.querySelector('[data-sessions-chip]')?.getAttribute('aria-describedby')).toBe(
      note?.id,
    );
    expect(result()).toBe('');
    expect(rows()).toBe(12);
    expect(screen.queryByRole('button', { name: 'Drift recorded' })).toBeNull();
  });
});

describe('the window control on a board of every stored session', () => {
  it('says recently active, not a window nobody published, when window_hours is absent', async () => {
    const { window_hours: _window, ...payload } = sessionsSearchPayload({ showAll: true });
    await open(payload);
    expect(document.querySelector('[data-sessions-all-note]')?.textContent).toContain(
      'Sessions that were not recently active were not fully read',
    );
    expect(screen.getByRole('link', { name: 'Show only recently active sessions' })).toBeVisible();
  });
});

describe('the Find a project field', () => {
  const many = () => {
    const payload = sessionsSearchPayload() as Row;
    const extra = ['alpha', 'beta', 'gamma', 'delta', 'epsilon'].map((name, index) => ({
      harness: 'claude',
      sid: `extra${String(index)}abcdef`,
      title: `Work in ${name}`,
      project: `team/${name}`,
      state: 'idle',
      last_activity: GENERATED - 60 * (index + 1),
    }));
    return { ...payload, sessions: [...(payload['sessions'] as Row[]), ...extra] } as Row;
  };

  it('narrows a long list without choosing, and keeps the words when the panel reopens', async () => {
    const page = await open(many());
    let popup = await openFilter(page, 'project');
    const find = within(popup).getByLabelText('Find a project') as HTMLInputElement;
    find.value = 'team';
    fireEvent.input(find);
    await page.settle();
    expect(popup.textContent).toContain('Showing 5 of 10 projects. Keep typing to narrow.');
    expect(chips()).toEqual([]);
    fireEvent.keyDown(find, { key: 'Escape' });
    await page.settle();
    popup = await openFilter(page, 'project');
    expect((within(popup).getByLabelText('Find a project') as HTMLInputElement).value).toBe('team');
    expect(popup.textContent).toContain('Showing 5 of 10 projects.');
    await pick(page, popup, 'team/alpha');
    expect(chips()).toEqual(['Project: team/alpha']);
    expect(screen.getByRole('button', { name: 'Clear project filter' })).toBeTruthy();
    await press(page, screen.getByRole('button', { name: 'Clear project filter' }));
    expect(chips()).toEqual([]);
  });

  it('lets no narrowing outlive its field when the list shrinks and grows again', async () => {
    const page = await open(many());
    const popup = await openFilter(page, 'project');
    const find = within(popup).getByLabelText('Find a project') as HTMLInputElement;
    find.value = 'team';
    fireEvent.input(find);
    await page.settle();
    await closeFilters(page);
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1 }));
    await page.poll({ ...many(), generated: GENERATED + 2 });
    const again = await openFilter(page, 'project');
    expect((within(again).getByLabelText('Find a project') as HTMLInputElement).value).toBe('');
    expect(again.textContent).not.toContain('Keep typing to narrow.');
    expect(again.querySelectorAll('[data-filter-option^="project:"]')).toHaveLength(10);
  });
});

describe('the field', () => {
  it('opens the one session a pasted id finds on Enter, and Escape empties the words', async () => {
    const page = await open();
    await type(page, SIDS.C.slice(0, 8));
    expect(result()).toContain('Press Enter to open it.');
    fireEvent.keyDown(field(), { key: 'Enter' });
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({ view: 'session', session: SIDS.C });
  });

  it('empties the words on Escape and on the clear button', async () => {
    const page = await open();
    await type(page, 'release');
    expect(rows()).toBe(2);
    fireEvent.keyDown(field(), { key: 'Escape' });
    await page.settle();
    expect(field().value).toBe('');
    expect(rows()).toBe(12);
    await type(page, 'release');
    await press(page, screen.getByRole('button', { name: 'Clear search' }));
    expect(field().value).toBe('');
    expect(rows()).toBe(12);
  });

  it('takes "/" from anywhere on the page', async () => {
    const page = await open();
    fireEvent.keyDown(document.body, { key: '/' });
    await page.settle();
    expect(document.activeElement).toBe(field());
  });
});

describe('focus after a button that goes as it is pressed', () => {
  it('hands Include them to the Filters button', async () => {
    const page = await open();
    await press(page, await startedToday(page));
    const include = screen.getByRole('button', { name: 'Include them' });
    include.focus();
    await press(page, include);
    expect(screen.queryByRole('button', { name: 'Include them' })).toBeNull();
    expect(document.activeElement).toBe(preset('Filters'));
  });

  it('hands Clear project filter to the first project option', async () => {
    const page = await open();
    const popup = await openFilter(page, 'project');
    await pick(page, popup, 'compass');
    const clear = screen.getByRole('button', { name: 'Clear project filter' });
    clear.focus();
    await press(page, clear);
    expect(chips()).toEqual([]);
    expect(
      document.activeElement?.closest('[data-filter-option]')?.getAttribute('data-filter-option'),
    ).toBe('project:compass');
  });

  it('hands Filter by last active instead to the Filters button', async () => {
    const page = await open();
    await pick(page, await openFilter(page, 'date'), 'Yesterday');
    await closeFilters(page);
    const switchDate = preset('Filter by last active instead');
    switchDate.focus();
    await press(page, switchDate);
    expect(document.activeElement).toBe(preset('Filters'));
    expect(chips()).toEqual(['Last active: Yesterday']);
  });

  it('returns a group’s Clear filters to the field with every choice and the words gone', async () => {
    const page = await open();
    await type(page, 'release');
    await press(page, tab('Waiting on you'));
    await press(page, tab('All'));
    const state = await openFilter(page, 'state');
    await pick(page, state, 'Working');
    await closeFilters(page);
    const line = document.querySelector<HTMLElement>('[data-next-sessions-shown="active"]');
    const clear = within(line as HTMLElement).getByRole('button', { name: 'Clear filters' });
    clear.focus();
    await press(page, clear);
    expect(rows()).toBe(12);
    expect(field().value).toBe('');
    expect(chips()).toEqual([]);
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
    expect(document.activeElement).toBe(field());
  });
});

describe('names that hold the words on screen', () => {
  it('names a shortened chip by its words and describes it by the whole list', async () => {
    const page = await open();
    const popup = await openFilter(page, 'project');
    await pick(page, popup, 'compass');
    await pick(page, popup, 'projects/pendulum-of-despair');
    await closeFilters(page);
    const chip = screen.getByRole('button', { name: 'Remove Project: compass +1 more' });
    const described = (chip.getAttribute('aria-describedby') ?? '')
      .split(' ')
      .map((id) => document.getElementById(id)?.textContent);
    expect(described).toEqual(['Project: compass, projects/pendulum-of-despair']);
  });

  it('names the guard’s link by the words it shows', async () => {
    const page = await open();
    await pick(page, await openFilter(page, 'project'), 'recce-cloud-infra');
    await closeFilters(page);
    const guard = document.querySelector<HTMLElement>('[data-sessions-hidden-waiting]');
    expect(
      within(guard as HTMLElement).getByRole('link', { name: 'Open it: Combat Completion' }),
    ).toBeTruthy();
  });
});

describe('the hidden-waiting guard across polls', () => {
  it('surfaces a session that starts waiting behind the filters at the next board', async () => {
    const page = await open();
    await pick(page, await openFilter(page, 'project'), 'recce-cloud-infra');
    await closeFilters(page);
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1, bWaiting: true }));
    const guard = document.querySelector<HTMLElement>('[data-sessions-hidden-waiting]');
    expect(guard?.textContent).toContain('2 sessions waiting on you are hidden by these filters.');
    expect(
      within(guard as HTMLElement)
        .getByRole('link', { name: 'See them on Needs you' })
        .getAttribute('href'),
    ).toBe('#n=attention');
    expect(within(guard as HTMLElement).queryByRole('link', { name: /^Open it/ })).toBeNull();
  });

  it('shows the wait footnote beside an empty Waiting on you result', async () => {
    const page = await open();
    await press(page, tab('Waiting on you'));
    await pick(page, await openFilter(page, 'drift'), 'Drift recorded');
    expect(
      [...document.querySelectorAll('[data-sessions-wait-coverage]')].map((one) => one.textContent),
    ).toEqual([
      'Gemini and Goose do not report when a session is waiting, so 2 of their sessions could be waiting without showing here.',
      'Codex, OpenCode and Pi report a wait only in some setups. See coverage on Needs you.',
    ]);
  });
});

describe('when nothing matches', () => {
  it('offers a single reset and keeps the older sessions link below the list', async () => {
    const page = await open();
    await type(page, 'quarterly invoices');
    expect(nothing()?.querySelector('p')?.textContent).toBe('Nothing here matches.');
    expect(document.querySelectorAll('[data-next-sessions-filtered-empty]')).toHaveLength(0);
    const older = screen.getByRole('link', { name: 'Show older sessions' });
    expect(older.getAttribute('href')).toContain('?all=1#n=sessions');
    expect(older.parentElement?.textContent).toContain('Your filters are not kept.');
    await press(page, preset('Show everything'));
    expect(rows()).toBe(12);
    expect(document.activeElement).toBe(field());
  });
});

describe('an empty board and an empty group', () => {
  it('keeps board counts at zero and restores a chosen tab when rows return', async () => {
    const page = await open();
    await press(page, tab('Waiting on you'));
    await page.poll({ ...sessionsSearchPayload({ generated: GENERATED + 1 }), sessions: [] });
    expect(tab('All').textContent).toBe('All 0');
    expect(document.querySelectorAll('[data-next-sessions-shown]')).toHaveLength(0);
    // The choice is still held, and the next board with rows is filtered by it.
    const history = (sessionsSearchPayload()['sessions'] as Row[]).filter(
      (row) => ![SIDS.A, SIDS.B, SIDS.C, SIDS.D].includes(row['sid'] as never),
    );
    await page.poll({
      ...sessionsSearchPayload({ generated: GENERATED + 2 }),
      asks: [],
      sessions: history,
    });
    expect(chips()).toEqual(['Waiting on you']);
    const active = document.querySelector('[data-next-operation-group="active"]');
    expect(active?.querySelector('[data-sessions-group-count]')?.textContent).toBe('0 sessions');
    expect(active?.querySelector('[data-next-sessions-shown]')).toBeNull();
  });
});

describe('the keys the field and the page share', () => {
  it('leaves "/" alone while the Filters panel is open', async () => {
    const page = await open();
    await openFilter(page, 'state');
    const state = preset('Filters');
    state.focus();
    const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });
    state.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(state);
  });

  it('leaves "/" alone in the Find a project field', async () => {
    const payload = sessionsSearchPayload() as Row;
    const extra = ['alpha', 'beta', 'gamma', 'delta', 'epsilon'].map((name, index) => ({
      harness: 'claude',
      sid: `extra${String(index)}abcdef`,
      title: `Work in ${name}`,
      project: `team/${name}`,
      state: 'idle',
      last_activity: GENERATED - 60 * (index + 1),
    }));
    const page = await open({
      ...payload,
      sessions: [...(payload['sessions'] as Row[]), ...extra],
    });
    const popup = await openFilter(page, 'project');
    const find = within(popup).getByLabelText('Find a project');
    find.focus();
    const event = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });
    find.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(find);
  });

  it('opens nothing on Enter during a composition or when several rows match', async () => {
    const page = await open();
    await type(page, SIDS.C.slice(0, 8));
    fireEvent.keyDown(field(), { key: 'Enter', isComposing: true });
    await page.settle();
    expect(page.router.getRoute().view).toBe('sessions');
    await type(page, 'release');
    expect(rows()).toBe(2);
    fireEvent.keyDown(field(), { key: 'Enter' });
    await page.settle();
    expect(page.router.getRoute().view).toBe('sessions');
  });

  it('reads the live words on Enter while the rows still show an earlier match', async () => {
    const page = await open();
    await type(page, SIDS.C.slice(0, 8));
    expect(result()).toContain('Press Enter to open it.');
    // Outside act, so the keystroke's own render commits and the deferred one has not yet run.
    const scope = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    scope.IS_REACT_ACT_ENVIRONMENT = false;
    try {
      const node = field();
      node.value = `${SIDS.C}zzzz`;
      node.dispatchEvent(new Event('input', { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
      expect(result()).not.toContain('Press Enter to open it.');
      node.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
      );
    } finally {
      scope.IS_REACT_ACT_ENVIRONMENT = true;
    }
    await page.settle();
    expect(page.router.getRoute().view).toBe('sessions');
  });
});

it('keeps the count on every tab equal to its unfiltered rows and independent of search', async () => {
  const page = await open();
  const tabs = within(screen.getByRole('group', { name: 'Session status' }));
  const buttons = tabs.getAllByRole('button');
  expect(buttons).toHaveLength(6);
  const names = buttons.map((button) => button.textContent);
  for (const button of buttons) {
    await press(page, button);
    expect(rows()).toBe(Number(button.textContent?.match(/\d+$/)?.[0]));
    expect(button.getAttribute('aria-pressed')).toBe('true');
  }
  await type(page, 'quarterly invoices');
  expect(rows()).toBe(0);
  expect(tabs.getAllByRole('button').map((button) => button.textContent)).toEqual(names);
});

it('keeps the rows visible when progress levels cannot be filtered', async () => {
  const page = await open({
    generated: GENERATED,
    annotate: true,
    sessions: [
      { harness: 'claude', sid: 'saved', project: 'p', annotation_goal: 'Ship' },
      { harness: 'codex', sid: 'empty', project: 'p', annotation_goal: '' },
    ],
  });
  await press(page, screen.getByRole('button', { name: 'Filters' }));
  const group = within(screen.getByRole('group', { name: 'Progress check' }));
  for (const name of ['Slightly off course', 'Off course', 'Way off course']) {
    const chip = group.getByRole('button', { name });
    await press(page, chip);
    expect(rows(), name).toBe(2);
    expect((chip as HTMLButtonElement).disabled).toBe(true);
  }
  expect(
    group.getByText(
      "Progress levels are shown on each session's page. Filtering this list by level is not available yet.",
    ),
  ).toBeVisible();
});

it('filters for no goal only when the board publishes that absence', async () => {
  const page = await open({
    generated: GENERATED,
    annotate: true,
    sessions: [
      { harness: 'claude', sid: 'saved', project: 'p', annotation_goal: 'Ship' },
      { harness: 'codex', sid: 'empty', project: 'p', annotation_goal: '' },
      { harness: 'claude', sid: 'unpublished', project: 'p' },
    ],
  });
  await press(page, screen.getByRole('button', { name: 'Filters' }));
  const group = within(screen.getByRole('group', { name: 'Progress check' }));
  const noGoal = group.getByRole('button', { name: 'No goal yet' });
  await press(page, noGoal);
  expect(rows()).toBe(1);
  expect(document.querySelector('[data-next-session="empty"]')).toBeInTheDocument();

  await closeFilters(page);
  await page.poll({
    generated: GENERATED + 1,
    annotate: true,
    sessions: [{ harness: 'claude', sid: 'unpublished', project: 'p' }],
  });
  expect(rows()).toBe(1);
  expect(document.querySelector('[data-next-session="unpublished"]')).toBeInTheDocument();
  await openPanel(page);
  const updated = within(screen.getByRole('group', { name: 'Progress check' }));
  expect(updated.getByRole<HTMLButtonElement>('button', { name: 'No goal yet' }).disabled).toBe(
    true,
  );
  expect(
    updated.getByText(/The board did not publish saved goals for these sessions\./),
  ).toBeVisible();
});

it('words the start hint with the displayed board clock', async () => {
  const page = await open();
  await pick(page, await openFilter(page, 'date'), 'Last 7 days');
  const row = document.querySelector(`[data-next-session="${SIDS.C}"]`);
  expect(row?.querySelector('[data-next-row-hint]')?.textContent).toBe(
    'Started yesterday, from the first message',
  );
});
