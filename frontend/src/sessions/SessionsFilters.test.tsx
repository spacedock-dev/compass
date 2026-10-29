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
