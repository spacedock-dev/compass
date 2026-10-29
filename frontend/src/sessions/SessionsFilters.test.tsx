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

async function press(page: Page, node: Element) {
  fireEvent.click(node);
  await page.settle();
}

async function openFilter(page: Page, facet: string, name: string) {
  await press(page, screen.getByRole('button', { name: new RegExp(`^${name}(,|$)`) }));
  const popup = document.querySelector<HTMLElement>(`[data-filter-popover="${facet}"]`);
  expect(popup).not.toBeNull();
  return popup as HTMLElement;
}

async function pick(page: Page, popup: HTMLElement, label: string) {
  await press(page, within(popup).getByText(label, { exact: true }));
}

async function type(page: Page, text: string) {
  const node = field();
  node.value = text;
  fireEvent.input(node);
  await page.settle();
}

async function closeFilters(page: Page) {
  fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
  await page.settle();
}

const trigger = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}(,|$)`) });
const nothing = () => document.querySelector('[data-sessions-nothing]');

describe('the presets and chips', () => {
  it('sets one value per preset, names it in a chip, and clears it from the chip', async () => {
    const page = await open();
    expect(result()).toBe('12 sessions active in the last 24 hours.');
    await press(page, preset('Waiting on you'));
    expect(preset('Waiting on you').getAttribute('aria-pressed')).toBe('true');
    expect(chips()).toEqual(['State: Waiting on you']);
    expect(result()).toBe(
      'Showing 1 of 12 sessions. ACTIVE NOW and WORKING above count the whole board. Press Enter to open it.',
    );
    expect(rows()).toBe(1);
    await press(page, preset('Started today'));
    expect(chips()).toEqual(['Started: Today', 'State: Waiting on you']);
    await press(page, preset('Drift recorded'));
    // Waiting and drift recorded are different rows, so nothing is left, and the empty state says why.
    expect(document.querySelector('[data-sessions-nothing]')?.textContent).toContain(
      'No session matches these filters.',
    );
    await press(page, preset('Drift recorded'));
    await press(page, preset('Started today'));
    expect(preset('Started today').getAttribute('aria-pressed')).toBe('false');
    await press(page, screen.getByRole('button', { name: 'Remove State: Waiting on you' }));
    expect(chips()).toEqual([]);
    expect(rows()).toBe(12);
  });

  it('clears everything at once and returns the reader to the field', async () => {
    const page = await open();
    await type(page, 'release');
    await press(page, preset('Waiting on you'));
    expect(result()).toContain('Showing 0 of 12');
    await press(page, screen.getByRole('button', { name: 'Clear all' }));
    expect(field().value).toBe('');
    expect(chips()).toEqual([]);
    expect(rows()).toBe(12);
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
  });

  it('toggles a facet value inside its popover and badges the trigger', async () => {
    const page = await open();
    const state = await openFilter(page, 'state', 'State');
    await pick(page, state, 'Working');
    expect(screen.getByRole('button', { name: 'State, 1 selected' })).toBeTruthy();
    expect(rows()).toBe(2);
    const harness = await openFilter(page, 'harness', 'Harness');
    await pick(page, harness, 'Codex');
    expect(chips()).toEqual(['Harness: Codex', 'State: Working']);
    expect(rows()).toBe(1);
  });
});

describe('what the cue region says', () => {
  it('speaks a press at once and typing only after the reader pauses', async () => {
    const page = await open();
    await press(page, preset('Waiting on you'));
    expect(cue()).toBe('Showing 1 of 12 sessions.');
    // The same count after a second press is spoken again: a fresh write, not the old node.
    const before = document.querySelector('#next-cockpit-cue-status')?.firstChild;
    const project = await openFilter(page, 'project', 'Project');
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
    await press(page, preset('Waiting on you'));
    const said = document.querySelector('#next-cockpit-cue-status')?.firstChild;
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1 }));
    expect(document.querySelector('#next-cockpit-cue-status')?.firstChild).toBe(said);
  });
});

describe('choices the board cannot apply', () => {
  it('disables Started today and claims no date filter when the board published no clock', async () => {
    const { generated: _clock, ...payload } = sessionsSearchPayload();
    const page = await open(payload);
    expect((preset('Started today') as HTMLButtonElement).disabled).toBe(true);
    const date = await openFilter(page, 'date', 'Date');
    expect(date.textContent).toContain(
      'The board published no clock time, so dates cannot be filtered.',
    );
    expect(result()).not.toContain('Showing');
  });

  it('keeps a date chip after the board stops publishing a clock, and says why it filters nothing', async () => {
    const page = await open();
    await press(page, preset('Started today'));
    expect(rows()).toBe(5);
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

  it('draws no Drift preset and lists no drift or goal while the annotation store cannot be read', async () => {
    const page = await open();
    await press(page, preset('Drift recorded'));
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1, unreadable: true }));
    expect(screen.queryByRole('button', { name: 'Drift recorded' })).toBeNull();
    expect(chips()).toEqual(['Drift: Drift recorded']);
    expect(document.querySelector('[data-sessions-chip-note]')?.textContent).toBe(
      'The annotation store could not be read, so drift and goals cannot be filtered. The Drift chip filters nothing.',
    );
    expect(rows()).toBe(12);
    for (const [facet, name] of [
      ['drift', 'Drift'],
      ['goal', 'Goal'],
    ] as const) {
      const popup = await openFilter(page, facet, name);
      expect(popup.querySelector('[data-sessions-annotations-off]')?.textContent).toBe(
        'The annotation store could not be read, so drift and goals cannot be filtered.',
      );
      expect(popup.querySelector('[data-filter-option]')).toBeNull();
      await closeFilters(page);
    }
    await press(page, screen.getByRole('button', { name: 'Remove Drift: Drift recorded' }));
    expect(cue()).toBe('Filters cleared. Showing all 12 sessions.');
  });

  it('never says filters were cleared for a setting changed while nothing is chosen', async () => {
    const page = await open();
    const date = await openFilter(page, 'date', 'Date');
    await press(page, within(date).getByRole('radio', { name: 'Last active' }));
    expect(cue()).toBe('Showing all 12 sessions.');
  });

  it('keeps a drift chip after annotations go off, says why it filters nothing, and claims no filter', async () => {
    const page = await open();
    await press(page, preset('Drift recorded'));
    expect(rows()).toBe(1);
    await page.poll(sessionsSearchPayload({ annotate: false }));
    expect(chips()).toEqual(['Drift: Drift recorded']);
    const note = document.querySelector('[data-sessions-chip-note]');
    expect(note?.textContent).toBe(
      'Drift is not published because annotations are off. The Drift chip filters nothing.',
    );
    expect(document.querySelector('[data-sessions-chip]')?.getAttribute('aria-describedby')).toBe(
      note?.id,
    );
    expect(result()).toBe('12 sessions active in the last 24 hours.');
    expect(rows()).toBe(12);
    expect(screen.queryByRole('button', { name: 'Drift recorded' })).toBeNull();
  });
});

describe('the Date popover on a board of every stored session', () => {
  it('says recently active, not a window nobody published, when window_hours is absent', async () => {
    const { window_hours: _window, ...payload } = sessionsSearchPayload({ showAll: true });
    const page = await open(payload);
    const date = await openFilter(page, 'date', 'Date');
    expect(date.querySelector('[data-sessions-all-note]')?.textContent).toBe(
      'Showing all stored sessions. Sessions that were not recently active were not fully read, so their start time, title or model may not be published.Show only recently active sessions',
    );
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

  it('narrows a long list without choosing, and keeps the words when the popover reopens', async () => {
    const page = await open(many());
    let popup = await openFilter(page, 'project', 'Project');
    const find = within(popup).getByLabelText('Find a project') as HTMLInputElement;
    find.value = 'team';
    fireEvent.input(find);
    await page.settle();
    expect(popup.textContent).toContain('Showing 5 of 10 projects. Keep typing to narrow.');
    expect(chips()).toEqual([]);
    fireEvent.keyDown(find, { key: 'Escape' });
    await page.settle();
    popup = await openFilter(page, 'project', 'Project');
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
    const popup = await openFilter(page, 'project', 'Project');
    const find = within(popup).getByLabelText('Find a project') as HTMLInputElement;
    find.value = 'team';
    fireEvent.input(find);
    await page.settle();
    await closeFilters(page);
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1 }));
    await page.poll({ ...many(), generated: GENERATED + 2 });
    const again = await openFilter(page, 'project', 'Project');
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
  it('hands Include them to the Date button', async () => {
    const page = await open();
    await press(page, preset('Started today'));
    const include = screen.getByRole('button', { name: 'Include them' });
    include.focus();
    await press(page, include);
    expect(screen.queryByRole('button', { name: 'Include them' })).toBeNull();
    expect(document.activeElement).toBe(trigger('Date'));
  });

  it('hands Clear project filter to the first project option', async () => {
    const page = await open();
    const popup = await openFilter(page, 'project', 'Project');
    await pick(page, popup, 'compass');
    const clear = screen.getByRole('button', { name: 'Clear project filter' });
    clear.focus();
    await press(page, clear);
    expect(chips()).toEqual([]);
    expect(
      document.activeElement?.closest('[data-filter-option]')?.getAttribute('data-filter-option'),
    ).toBe('project:compass');
  });

  it('hands Filter by last active instead to the Date button, or to its radio inside the popover', async () => {
    const page = await open();
    const date = await openFilter(page, 'date', 'Date');
    await pick(page, date, 'Yesterday');
    const inside = within(date).getByRole('button', { name: 'Filter by last active instead' });
    inside.focus();
    await press(page, inside);
    expect(
      document.activeElement?.closest('[data-filter-option]')?.getAttribute('data-filter-option'),
    ).toBe('date-field:active');
    await press(page, within(date).getByRole('radio', { name: 'Started' }));
    await closeFilters(page);
    const note = document.querySelector<HTMLElement>(
      '[data-next-sessions-search] > [data-sessions-window-note="started"]',
    );
    const outside = within(note as HTMLElement).getByRole('button', {
      name: 'Filter by last active instead',
    });
    outside.focus();
    await press(page, outside);
    expect(document.activeElement).toBe(trigger('Date'));
  });

  it('returns a group’s Clear filters to the field with every choice and the words gone', async () => {
    const page = await open();
    await type(page, 'release');
    await press(page, preset('Waiting on you'));
    await press(page, preset('Waiting on you'));
    const state = await openFilter(page, 'state', 'State');
    await pick(page, state, 'Idle');
    await closeFilters(page);
    const line = document.querySelector<HTMLElement>('[data-next-sessions-shown="history"]');
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
    const popup = await openFilter(page, 'project', 'Project');
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
    await pick(page, await openFilter(page, 'project', 'Project'), 'recce-cloud-infra');
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
    await pick(page, await openFilter(page, 'project', 'Project'), 'recce-cloud-infra');
    await closeFilters(page);
    await page.poll(sessionsSearchPayload({ generated: GENERATED + 1, bWaiting: true }));
    const guard = document.querySelector<HTMLElement>('[data-sessions-hidden-waiting]');
    expect(guard?.textContent).toContain('2 sessions waiting on you are hidden by these filters.');
    expect(
      within(guard as HTMLElement).getByRole('link', { name: 'See them on Attention' }),
    ).toBeTruthy();
    expect(within(guard as HTMLElement).queryByRole('link', { name: /^Open it/ })).toBeNull();
  });

  it('shows the wait footnote beside an empty Waiting on you result', async () => {
    const page = await open();
    await press(page, preset('Waiting on you'));
    await press(page, preset('Drift recorded'));
    expect(
      [...(nothing()?.querySelectorAll('[data-sessions-wait-coverage]') ?? [])].map(
        (one) => one.textContent,
      ),
    ).toEqual([
      'Gemini and Goose do not report when a session is waiting, so 2 of their sessions could be waiting without showing here.',
      "Codex, OpenCode and Pi report a wait only in some setups; Attention's coverage says which.",
    ]);
  });
});

describe('when nothing matches', () => {
  it('names the sessions marked handled, one or several', async () => {
    let page = await open({ ...sessionsSearchPayload(), cleared: 2 } as Row);
    await type(page, 'zzzz');
    expect(nothing()?.textContent).toContain(
      '2 sessions you marked handled are not on this board.',
    );
    page.unmount();
    page = await open({ ...sessionsSearchPayload(), cleared: 1 } as Row);
    await type(page, 'zzzz');
    expect(nothing()?.textContent).toContain('1 session you marked handled is not on this board.');
  });

  it('says recently active, not a window nobody published, on the default board without window_hours', async () => {
    const { window_hours: _window, ...payload } = sessionsSearchPayload();
    const page = await open(payload);
    const date = await openFilter(page, 'date', 'Date');
    await pick(page, date, 'Yesterday');
    await closeFilters(page);
    expect(
      document.querySelector('[data-next-sessions-search] > [data-sessions-window-note]')
        ?.textContent,
    ).toBe('The board holds only recently active sessions.');
    await type(page, 'zzzz');
    expect(nothing()?.textContent).toContain('Sessions not recently active are not loaded.');
    expect(
      within(nothing() as HTMLElement).getByRole('link', { name: 'Show all stored sessions' }),
    ).toBeTruthy();
  });
});

describe('an empty board and an empty group', () => {
  it('draws no toolbar over an empty board, and keeps a group’s own sentence when it has no rows', async () => {
    const page = await open();
    await press(page, preset('Waiting on you'));
    await page.poll({ ...sessionsSearchPayload({ generated: GENERATED + 1 }), sessions: [] });
    expect(screen.queryByRole('search', { name: 'Find sessions' })).toBeNull();
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
    expect(chips()).toEqual(['State: Waiting on you']);
    const active = document.querySelector('[data-next-operation-group="active"]');
    expect(active?.querySelector('.next-sessions-empty')?.textContent).toBe(
      'No exact session has active evidence right now.',
    );
    expect(active?.querySelector('[data-next-sessions-shown]')).toBeNull();
  });
});

describe('the keys the field and the page share', () => {
  it('leaves "/" alone while a filter popover is open or focus is in Find a project', async () => {
    const page = await open();
    await openFilter(page, 'state', 'State');
    const state = trigger('State');
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
    const popup = await openFilter(page, 'project', 'Project');
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
