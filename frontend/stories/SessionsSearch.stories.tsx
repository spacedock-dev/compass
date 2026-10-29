import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { act, useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import type { Shell } from '../src/shell/context';
import { createFakeClock, createFakeEnvironment, type FakeClock } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import {
  GENERATED,
  SIDS,
  sessionsSearchPayload,
  type FixtureOptions,
} from './sessionsSearch.fixture';

/* Sessions search and filters (docs/design-sessions-search.md), the stories the owner signed off. Every story
   mounts the real page over a static board of twelve rows; a poll is the story calling the runtime's refresh
   with the board's clock moved on a second. Nothing here is a production path: the counts the stories
   assert were worked out by hand from the fixture, so a figure that disagrees is the page's to explain. */

interface Rig {
  readonly shell: Shell;
  readonly history: ReturnType<typeof fakeRouterEnvironment>;
  readonly clock: FakeClock;
  readonly live: { -readonly [K in keyof FixtureOptions]: FixtureOptions[K] } & {
    generated: number;
  };
}

let rig: Rig | null = null;
const current = (): Rig => {
  if (!rig) throw new Error('The board has not mounted.');
  return rig;
};

function Board({
  annotate = true,
  showAll = false,
}: {
  readonly annotate?: boolean;
  readonly showAll?: boolean;
}) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment('#n=sessions');
    const clock = createFakeClock();
    const live: Rig['live'] = { generated: GENERATED, annotate, showAll };
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    const made = createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: showAll ? '?all=1' : '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          url.startsWith('/api/data') ? json(sessionsSearchPayload({ ...live })) : json({}),
        ),
    });
    rig = { shell: made, history, clock, live };
    return made;
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}

const meta = {
  title: 'Sessions/Search and filters',
  component: Board,
} satisfies Meta<typeof Board>;
export default meta;
type Story = StoryObj<typeof meta>;

const letterOf = (sid: string): string =>
  Object.entries(SIDS).find(([, value]) => value === sid)?.[0] ?? sid;
const shownRows = (root: HTMLElement): string =>
  [...root.querySelectorAll('article.next-operation-row')]
    .map((row) => letterOf(row.getAttribute('data-next-session') ?? ''))
    .sort()
    .join('');
const rowOf = (root: HTMLElement, letter: keyof typeof SIDS) =>
  root.querySelector<HTMLElement>(
    `article.next-operation-row[data-next-session="${SIDS[letter]}"]`,
  );
const resultText = (root: HTMLElement) =>
  root.querySelector('[data-sessions-result]')?.textContent ?? '';
const shownLines = (root: HTMLElement) =>
  [...root.querySelectorAll('[data-next-sessions-shown-count]')].map((one) => one.textContent);
const chips = (root: HTMLElement) =>
  [...root.querySelectorAll('[data-sessions-chip]')].map((one) => one.textContent);
const headerText = (root: HTMLElement, kind: 'active' | 'history') =>
  root.querySelector(`[data-next-operation-group="${kind}"] > header`)?.textContent ?? '';
const cue = (root: HTMLElement) => root.querySelector('#next-cockpit-cue-status') as HTMLElement;
const ACTIVE_HEADER = 'Active nowworking, waiting on you, an exact request, or recorded drift';
const HISTORY_HEADER = 'Recent historyWhat recent means';

async function ready(root: HTMLElement) {
  const canvas = within(root);
  await canvas.findByRole('search', { name: 'Find sessions' });
  await waitFor(() => expect(shownRows(root)).toHaveLength(12));
  return canvas;
}

const trigger = (root: HTMLElement, name: string) =>
  within(root).getByRole('button', { name: new RegExp(`^${name}(,|$)`) });

async function openFilter(root: HTMLElement, facet: string, name: string) {
  const button = trigger(root, name);
  await userEvent.click(button);
  await waitFor(() => expect(button).toHaveAttribute('aria-expanded', 'true'));
  const popup = root.querySelector<HTMLElement>(`[data-filter-popover="${facet}"]`);
  await expect(popup).not.toBeNull();
  return popup as HTMLElement;
}

async function closeFilters() {
  await userEvent.keyboard('{Escape}');
}

const options = (popup: HTMLElement, facet: string) =>
  [...popup.querySelectorAll<HTMLElement>(`[data-filter-option^="${facet}:"]`)].map((row) => ({
    label: row.querySelector('[data-filter-label]')?.textContent ?? '',
    count: row.querySelector('[data-filter-count]')?.textContent ?? null,
    note: row.querySelector('[data-filter-note]')?.textContent ?? '',
    box: row.querySelector<HTMLElement>('[role=checkbox], [role=radio]'),
  }));

async function pick(popup: HTMLElement, label: string) {
  await userEvent.click(within(popup).getByText(label, { exact: true }));
}

async function poll(change: Partial<Rig['live']> = {}) {
  const { live, shell } = current();
  Object.assign(live, change);
  live.generated += 1;
  await shell.runtime.refresh();
}

async function atWidth(width: number, check: () => Promise<void>) {
  const browserPage =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (browserPage) await browserPage.viewport(width, 800);
  try {
    if (browserPage) await expect(window.innerWidth).toBe(width);
    await check();
  } finally {
    if (browserPage) await browserPage.viewport(before.width, before.height);
  }
}

const FOLLOWS = Node.DOCUMENT_POSITION_FOLLOWING;

/* A keydown dispatched by hand, inside React's act as userEvent's own presses are: for the body, for a field
   that does not have focus, and for an Enter that opens a session. userEvent's full Enter press left the
   session page's first reads settling outside act (measured: SessionDetail, IntentPanel and DriftProvider
   warnings), where a keydown alone does not. */
async function dispatchKey(target: EventTarget, key: string): Promise<KeyboardEvent> {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  const scope = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean | undefined };
  const was = scope.IS_REACT_ACT_ENVIRONMENT;
  scope.IS_REACT_ACT_ENVIRONMENT = true;
  try {
    await act(async () => {
      target.dispatchEvent(event);
    });
  } finally {
    scope.IS_REACT_ACT_ENVIRONMENT = was;
  }
  return event;
}

/* 1 */
export const DefaultBoard: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const search = canvas.getByRole('search', { name: 'Find sessions' });
    const fleet = canvas.getByRole('region', { name: 'Fleet facts' });
    const active = canvas.getByRole('heading', { level: 2, name: 'Active now' });
    await expect(fleet.compareDocumentPosition(search) & FOLLOWS).toBeTruthy();
    await expect(search.compareDocumentPosition(active) & FOLLOWS).toBeTruthy();
    await expect(resultText(canvasElement)).toBe('12 sessions active in the last 24 hours.');
    await expect(chips(canvasElement)).toEqual([]);
    const presets = within(canvas.getByRole('group', { name: 'Quick filters' })).getAllByRole(
      'button',
    );
    await expect(presets.map((one) => one.textContent)).toEqual([
      'Waiting on you',
      'Started today',
      'Drift recorded',
    ]);
    for (const preset of presets) await expect(preset).toHaveAttribute('aria-pressed', 'false');
    await expect(headerText(canvasElement, 'active')).toBe(ACTIVE_HEADER);
    await expect(headerText(canvasElement, 'history')).toBe(HISTORY_HEADER);
    await expect(shownLines(canvasElement)).toEqual([]);
    const facts = canvasElement.querySelector('[data-next-fleet-fact="active"]') as HTMLElement;
    await expect(facts.querySelector('strong')).toHaveTextContent('4');
    await expect(facts.querySelector('small')).toHaveTextContent('12 recently observed');
  },
};

/* 2 */
export const SearchByWords: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const fleet = canvas.getByRole('region', { name: 'Fleet facts' });
    const before = fleet.textContent;
    await userEvent.type(canvas.getByRole('searchbox', { name: 'Search sessions' }), 'release');
    await waitFor(() =>
      expect(resultText(canvasElement)).toBe(
        'Showing 2 of 12 sessions. ACTIVE NOW and WORKING above count the whole board.',
      ),
    );
    await expect(shownRows(canvasElement)).toBe('BK');
    await expect(shownLines(canvasElement)).toEqual(['1 of 4 shown', '1 of 8 shown']);
    await expect(
      rowOf(canvasElement, 'B')?.querySelector('[data-next-row-hint]'),
    ).toHaveTextContent('Matched in your first prompt: "write the release notes for 2.4"');
    await expect(rowOf(canvasElement, 'K')?.querySelector('[data-next-row-hint]')).toBeNull();
    const guard = canvasElement.querySelector('[data-sessions-hidden-waiting]') as HTMLElement;
    await expect(guard).toHaveTextContent('1 session waiting on you is hidden by these filters.');
    await expect(
      within(guard).getByRole('link', { name: 'Open it: Combat Completion' }),
    ).toBeVisible();
    await expect(fleet.textContent).toBe(before);
  },
};

/* 3 */
export const StartedTodayAndMissingStartTimes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const preset = canvas.getByRole('button', { name: 'Started today' });
    await userEvent.click(preset);
    await expect(preset).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('ABEFK'));
    const date = trigger(canvasElement, 'Date');
    await expect(date).toHaveAccessibleName('Date, 1 selected');
    await expect(date.querySelector('[data-filter-badge]')).toHaveTextContent('1');
    await expect(chips(canvasElement)).toEqual(['Started: Today']);
    await expect(canvasElement.querySelector('[data-sessions-unstamped]')).toHaveTextContent(
      '4 sessions have no published start time and are not shown.',
    );
    const popup = await openFilter(canvasElement, 'date', 'Date');
    await expect(popup.querySelector('[data-sessions-unstamped-harnesses]')).toHaveTextContent(
      'No start time is published for: Cursor, Goose, OpenCode, Pi.',
    );
    // The tall Date list opens under its button and scrolls there; it never flips beside it, over the search field.
    const shell = popup.closest<HTMLElement>('[data-slot=popover-content]') as HTMLElement;
    await waitFor(() => {
      const box = shell.getBoundingClientRect();
      const at = date.getBoundingClientRect();
      expect(box.right).toBeGreaterThan(at.left);
      expect(box.top).toBeGreaterThanOrEqual(at.bottom - 1);
      expect(box.bottom).toBeLessThanOrEqual(innerHeight);
    });
    await closeFilters();
    await userEvent.click(canvas.getByRole('button', { name: 'Include them' }));
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(9));
    // The button goes as it is pressed, and hands focus to the Date button rather than to the page.
    await expect(date).toHaveFocus();
    await expect(chips(canvasElement)).toEqual(['Started: Today, plus 4 with no start time']);
    const again = await openFilter(canvasElement, 'date', 'Date');
    const unstamped = options(again, 'when').find((one) => one.label === 'Start not published');
    await expect(unstamped?.count).toBe('4');
    await pick(again, 'Start not published');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('GHIJ'));
    await pick(again, 'Last 7 days');
    await waitFor(() =>
      expect(rowOf(canvasElement, 'C')?.querySelector('[data-next-row-hint]')).toHaveTextContent(
        'Started 2030-01-14 16:02, from the first message',
      ),
    );
  },
};

/* 4 */
export const DatesBeyondTheBoardWindow: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const popup = await openFilter(canvasElement, 'date', 'Date');
    await pick(popup, 'Yesterday');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('CDL'));
    await closeFilters();
    const search = canvas.getByRole('search', { name: 'Find sessions' });
    const started = search.querySelector(':scope > [data-sessions-window-note="started"]');
    await expect(started).toHaveTextContent(
      'The board holds sessions active since 2030-01-14 12:00 (the last 24 hours). A session that started in this range and went quiet before then is not on the board.',
    );
    await userEvent.click(
      within(started as HTMLElement).getByRole('button', { name: 'Filter by last active instead' }),
    );
    await waitFor(() => expect(shownRows(canvasElement)).toBe('L'));
    await expect(trigger(canvasElement, 'Date')).toHaveFocus();
    const note = search.querySelector(
      ':scope > [data-sessions-window-note="active"]',
    ) as HTMLElement;
    await expect(note).toHaveTextContent('Older sessions are not loaded.');
    await expect(note).toHaveTextContent('Your filters are not kept.');
    const link = within(note).getByRole('link', { name: 'Show all stored sessions' });
    await expect(link.getAttribute('href')?.endsWith('?all=1#n=sessions')).toBe(true);
    await pick(await openFilter(canvasElement, 'date', 'Date'), 'Today');
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(11));
    await expect(canvasElement.querySelector('[data-sessions-window-note]')).toBeNull();
  },
};

/* 5 */
export const ProjectAndHarness: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const popup = await openFilter(canvasElement, 'project', 'Project');
    const listed = options(popup, 'project');
    await expect(listed.map((one) => `${one.label} ${one.count ?? ''}`)).toEqual([
      'compass 2',
      'projects/pendulum-of-despair 2',
      'recce-cloud-infra 1',
      'recce/compass 6',
      'No project published 1',
    ]);
    await expect(listed[0]?.note).toBe('Label shared by more than one location');
    await expect(listed[3]?.note).toBe('');
    await expect(
      rowOf(canvasElement, 'B')?.querySelector('.next-operation-collision'),
    ).toHaveTextContent('6 sessions share this display label; shared location is not established');
    await pick(popup, 'compass');
    await pick(popup, 'recce/compass');
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(8));
    await expect(trigger(canvasElement, 'Project')).toHaveAccessibleName('Project, 2 selected');
    await closeFilters();
    await expect(chips(canvasElement)).toEqual(['Project: compass, recce/compass']);
    await expect(
      canvas.getByRole('button', { name: 'Remove Project: compass, recce/compass' }),
    ).toBeVisible();
    const again = await openFilter(canvasElement, 'project', 'Project');
    await userEvent.click(within(again).getByRole('button', { name: 'Clear project filter' }));
    await waitFor(() => expect(chips(canvasElement)).toEqual([]));
    await expect(options(again, 'project')[0]?.box).toHaveFocus();
    await closeFilters();
    const harness = await openFilter(canvasElement, 'harness', 'Harness');
    const harnesses = options(harness, 'harness');
    await expect(harnesses.map((one) => one.label)).toEqual([
      'Claude Code',
      'Codex',
      'Gemini',
      'Cursor',
      'Pi',
      'Goose',
      'OpenCode',
      'Droid',
    ]);
    const droid = harnesses.at(-1);
    await expect(droid?.note).toBe('Store could not be read');
    await expect(droid?.count).toBeNull();
    await expect(droid?.box).toHaveAttribute('aria-disabled', 'true');
    await expect(harness).not.toHaveTextContent(/Copilot|Antigravity/);
  },
};

/* 6 */
export const AWaitingSessionIsNeverHiddenSilently: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    await pick(await openFilter(canvasElement, 'project', 'Project'), 'recce-cloud-infra');
    await closeFilters();
    await waitFor(() => expect(shownRows(canvasElement)).toBe('I'));
    const guard = canvasElement.querySelector('[data-sessions-hidden-waiting]') as HTMLElement;
    await expect(guard).toHaveTextContent('1 session waiting on you is hidden by these filters.');
    await userEvent.click(within(guard).getByRole('link', { name: 'Open it: Combat Completion' }));
    const { shell, history } = current();
    await waitFor(() =>
      expect(shell.router.getRoute()).toMatchObject({ view: 'session', session: SIDS.A }),
    );
    history.back();
    history.flush();
    await waitFor(() => expect(shell.router.getRoute().view).toBe('sessions'));
    await waitFor(() => expect(chips(canvasElement)).toEqual(['Project: recce-cloud-infra']));
    await expect(canvas.getByRole('button', { name: /1 reported block/ })).toBeVisible();
    const back = canvasElement.querySelector('[data-sessions-hidden-waiting]') as HTMLElement;
    await userEvent.click(within(back).getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(12));
    await expect(canvas.getByRole('searchbox', { name: 'Search sessions' })).toHaveFocus();
  },
};

/* 7 */
export const NothingMatches: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    await expect(canvasElement.querySelectorAll('.next-sessions-empty')).toHaveLength(0);
    await userEvent.type(canvas.getByRole('searchbox', { name: 'Search sessions' }), 'zzzz');
    await waitFor(() => expect(shownRows(canvasElement)).toBe(''));
    const nothing = canvasElement.querySelector('[data-sessions-nothing]') as HTMLElement;
    await expect(nothing).toHaveTextContent('No session matches these filters.');
    await expect(nothing).toHaveTextContent(
      'Search reads titles, goals and prompts, not the conversation itself.',
    );
    await expect(nothing).toHaveTextContent(
      'Sessions not active in the last 24 hours are not loaded.',
    );
    await expect(
      within(nothing).getByRole('link', { name: 'Show all stored sessions' }),
    ).toBeVisible();
    await expect(shownLines(canvasElement)).toEqual(['0 of 4 shown', '0 of 8 shown']);
    await expect(
      [...canvasElement.querySelectorAll('[data-next-sessions-filtered-empty]')].map(
        (one) => one.textContent,
      ),
    ).toEqual([
      'None of the 4 sessions in Active now match these filters.',
      'None of the 8 sessions in Recent history match these filters.',
    ]);
    await expect(canvasElement.querySelectorAll('.next-sessions-empty')).toHaveLength(0);
    await expect(headerText(canvasElement, 'active')).toBe(ACTIVE_HEADER);
    await expect(headerText(canvasElement, 'history')).toBe(HISTORY_HEADER);
  },
};

/* 8 */
export const StateAndDrift: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const state = await openFilter(canvasElement, 'state', 'State');
    await pick(state, 'Waiting on you');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('A'));
    await expect(rowOf(canvasElement, 'A')?.querySelector('[data-next-row-state]')).toHaveAttribute(
      'data-next-row-state',
      'Waiting on you',
    );
    const coverage = [...state.querySelectorAll('[data-sessions-wait-coverage]')].map(
      (one) => one.textContent,
    );
    await expect(coverage).toEqual([
      'Gemini and Goose do not report when a session is waiting, so 2 of their sessions could be waiting without showing here.',
      "Codex, OpenCode and Pi report a wait only in some setups; Attention's coverage says which.",
    ]);
    await closeFilters();
    await userEvent.click(canvas.getByRole('button', { name: 'Clear all' }));
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(12));
    const drift = await openFilter(canvasElement, 'drift', 'Drift');
    const listed = options(drift, 'drift');
    await expect(listed.map((one) => one.count)).toEqual(['1', '1', '10']);
    for (const one of listed) await expect(one.label).not.toMatch(/no drift|on track/i);
    await pick(drift, 'Drift recorded');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('D'));
    await expect(
      rowOf(canvasElement, 'D')?.querySelector('[data-next-session-drift-mark]'),
    ).not.toBeNull();
    await expect(options(drift, 'drift')[0]?.box).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByRole('button', { name: 'Drift recorded' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  },
};

/* 9 */
export const Goal: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const goal = await openFilter(canvasElement, 'goal', 'Goal');
    const counts = options(goal, 'goal').map((one) => Number(one.count));
    await expect(counts.reduce((sum, one) => sum + one, 0)).toBe(12);
    await pick(goal, 'Goal saved');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('BK'));
    const after = options(goal, 'goal').map((one) => Number(one.count));
    await expect(after.reduce((sum, one) => sum + one, 0)).toBe(12);
  },
};

/* 10 */
export const FiltersSurviveAPollAndARoundTrip: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const box = canvas.getByRole('searchbox', { name: 'Search sessions' }) as HTMLInputElement;
    await userEvent.type(box, 'release');
    await pick(await openFilter(canvasElement, 'project', 'Project'), 'recce/compass');
    await closeFilters();
    await waitFor(() => expect(chips(canvasElement)).toEqual(['Project: recce/compass']));
    box.focus();
    box.setSelectionRange(3, 3);
    const spoken = cue(canvasElement).textContent;
    await poll({ bIdle: true });
    await waitFor(() =>
      expect(
        canvasElement.querySelector(
          `[data-next-operation-group="history"] [data-next-session="${SIDS.B}"]`,
        ),
      ).not.toBeNull(),
    );
    await expect(box.value).toBe('release');
    await expect(box.selectionStart).toBe(3);
    await expect(box).toHaveFocus();
    await expect(chips(canvasElement)).toEqual(['Project: recce/compass']);
    await expect(shownLines(canvasElement)).toEqual(['0 of 3 shown', '2 of 9 shown']);
    await expect(cue(canvasElement).textContent).toBe(spoken);
    await userEvent.click(canvas.getByRole('link', { name: 'Open session Cut the 2.4 release' }));
    const { shell } = current();
    await waitFor(() => expect(shell.router.getRoute().view).toBe('session'));
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(shell.router.getRoute().view).toBe('sessions'));
    const restored = (await within(canvasElement).findByRole('searchbox', {
      name: 'Search sessions',
    })) as HTMLInputElement;
    await expect(restored.value).toBe('release');
    await expect(chips(canvasElement)).toEqual(['Project: recce/compass']);
    await waitFor(() => expect(shownRows(canvasElement)).toBe('BK'));
  },
};

/* 11 */
export const KeyboardAndEscape: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const { shell, history } = current();
    const box = canvas.getByRole('searchbox', { name: 'Search sessions' }) as HTMLInputElement;
    await expect(box).toHaveAttribute('aria-keyshortcuts', '/');
    (document.activeElement as HTMLElement | null)?.blur();
    const slash = await dispatchKey(document.body, '/');
    await expect(slash.defaultPrevented).toBe(true);
    await expect(box).toHaveFocus();
    await userEvent.keyboard('p');
    await expect(box.value).toBe('p');
    await expect(shell.router.getRoute().view).toBe('sessions');
    await userEvent.keyboard('{Escape}');
    await expect(box.value).toBe('');
    await expect(box).toHaveFocus();
    // Inside the Project popover, a letter belongs to the option, and Escape returns to the trigger.
    const project = trigger(canvasElement, 'Project');
    await openFilter(canvasElement, 'project', 'Project');
    await userEvent.tab();
    await expect(document.activeElement?.getAttribute('role')).toBe('checkbox');
    await userEvent.keyboard('p');
    await expect(shell.router.getRoute().view).toBe('sessions');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(project).toHaveAttribute('aria-expanded', 'false'));
    await expect(project).toHaveFocus();
    // The capture-phase popover Escape runs first, and the field leaves its words alone.
    await userEvent.type(box, 'rel');
    const date = trigger(canvasElement, 'Date');
    await openFilter(canvasElement, 'date', 'Date');
    await dispatchKey(box, 'Escape');
    await waitFor(() => expect(date).toHaveAttribute('aria-expanded', 'false'));
    await expect(box.value).toBe('rel');
    // A pasted id prefix that finds one session opens it on Enter.
    await userEvent.clear(box);
    box.focus();
    await userEvent.paste(SIDS.C.slice(0, 8));
    await waitFor(() => expect(resultText(canvasElement)).toContain('Press Enter to open it.'));
    await dispatchKey(box, 'Enter');
    await waitFor(() =>
      expect(shell.router.getRoute()).toMatchObject({ view: 'session', session: SIDS.C }),
    );
    await expect(history.env.getHash().startsWith('#n=session:')).toBe(true);
    // Straight back to Sessions, as story 10 does: a session page left mounted settles its reads after the story.
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard('{Escape}');
    await within(canvasElement).findByRole('search', { name: 'Find sessions' });
  },
};

/* 12 */
export const Announcements: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const region = cue(canvasElement);
    let writes = 0;
    const watch = new MutationObserver(() => {
      writes += 1;
    });
    watch.observe(region, { childList: true, characterData: true, subtree: true });
    try {
      const state = await openFilter(canvasElement, 'state', 'State');
      await pick(state, 'Waiting on you');
      await waitFor(() => expect(region).toHaveTextContent('Showing 1 of 12 sessions.'));
      await pick(state, 'Waiting on you');
      await waitFor(() =>
        expect(region).toHaveTextContent('Filters cleared. Showing all 12 sessions.'),
      );
      const before = writes;
      await pick(state, 'Waiting on you');
      await waitFor(() => expect(region).toHaveTextContent('Showing 1 of 12 sessions.'));
      await expect(writes).toBeGreaterThan(before);
      await closeFilters();
      // A second press that lands on the same count says it again, so the reader hears their press counted.
      const same = writes;
      await pick(
        await openFilter(canvasElement, 'project', 'Project'),
        'projects/pendulum-of-despair',
      );
      await waitFor(() => expect(writes).toBe(same + 1));
      await expect(region).toHaveTextContent('Showing 1 of 12 sessions.');
      await closeFilters();
      await userEvent.click(canvas.getByRole('button', { name: 'Clear all' }));
      await waitFor(() =>
        expect(region).toHaveTextContent('Filters cleared. Showing all 12 sessions.'),
      );
      /* Typing speaks once, after the reader pauses, and never the words. The announcer writes the region
         synchronously while the observer counts on a microtask, so each step reads the region's text at once
         and lets a microtask pass before it reads the count. */
      const typed = writes;
      await userEvent.type(canvas.getByRole('searchbox', { name: 'Search sessions' }), 'rel');
      await Promise.resolve();
      await expect(writes).toBe(typed);
      const { clock } = current();
      clock.advance(599);
      await expect(region).toHaveTextContent('Filters cleared. Showing all 12 sessions.');
      await Promise.resolve();
      await expect(writes).toBe(typed);
      clock.advance(1);
      await expect(region).toHaveTextContent('Showing 2 of 12 sessions.');
      await Promise.resolve();
      await expect(writes).toBe(typed + 1);
      await expect(region).not.toHaveTextContent('rel');
      const settled = writes;
      await poll();
      await waitFor(() => expect(shownRows(canvasElement)).toBe('BK'));
      await expect(writes).toBe(settled);
    } finally {
      watch.disconnect();
    }
  },
};

/* 13 */
export const PhoneWidth: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const search = canvas.getByRole('search', { name: 'Find sessions' });
    const box = canvas.getByRole('searchbox', { name: 'Search sessions' });
    for (const width of [400, 360])
      await atWidth(width, async () => {
        await waitFor(() =>
          expect(
            Math.abs(box.getBoundingClientRect().width - search.getBoundingClientRect().width),
          ).toBeLessThan(2),
        );
        await expect(search.querySelector('kbd')).not.toBeVisible();
        for (const button of search.querySelectorAll<HTMLElement>('button'))
          if (button.checkVisibility())
            await expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
        const popup = await openFilter(canvasElement, 'state', 'State');
        for (const row of popup.querySelectorAll<HTMLElement>('[data-filter-option]'))
          await expect(row.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
        const box2 = popup.closest('[data-slot=popover-content]') as HTMLElement;
        await expect(box2.getBoundingClientRect().right).toBeLessThanOrEqual(
          window.innerWidth - 16,
        );
        await closeFilters();
      });
    await userEvent.click(canvas.getByRole('button', { name: 'Waiting on you' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Started today' }));
    await pick(
      await openFilter(canvasElement, 'project', 'Project'),
      'projects/pendulum-of-despair',
    );
    await closeFilters();
    await waitFor(() => expect(chips(canvasElement)).toHaveLength(3));
    for (const width of [400, 360, 1280])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
  },
};

/* 14 */
export const AllStoredSessions: Story = {
  args: { showAll: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('search', { name: 'Find sessions' });
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(15),
    );
    await expect(resultText(canvasElement)).toBe('15 stored sessions.');
    const popup = await openFilter(canvasElement, 'date', 'Date');
    const note = popup.querySelector('[data-sessions-all-note]') as HTMLElement;
    await expect(note).toHaveTextContent(
      'Showing all stored sessions. Sessions not active in the last 24 hours were not fully read, so their start time, title or model may not be published.',
    );
    await waitFor(() =>
      expect(within(note).getByRole('link', { name: 'Show only the last 24 hours' })).toBeVisible(),
    );
    await pick(popup, 'Last 7 days');
    await closeFilters();
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-sessions-unstamped]')).toHaveTextContent(
        '7 sessions have no published start time and are not shown.',
      ),
    );
    await expect(shownRows(canvasElement)).toBe('ABCDEFKL');
  },
};

/* 15 */
export const AnnotationsOff: Story = {
  args: { annotate: false },
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const drift = await openFilter(canvasElement, 'drift', 'Drift');
    await expect(drift).toHaveTextContent('Drift is not published because annotations are off.');
    await closeFilters();
    const goal = await openFilter(canvasElement, 'goal', 'Goal');
    await expect(goal).toHaveTextContent('Goals are not published because annotations are off.');
    await closeFilters();
    await expect(canvas.queryByRole('button', { name: 'Drift recorded' })).toBeNull();
  },
};

/* 16 */
export const PaintHoldWhileAFilterIsOpen: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const { shell } = current();
    const counts = () =>
      options(
        canvasElement.querySelector<HTMLElement>('[data-filter-popover="state"]') as HTMLElement,
        'state',
      ).map((one) => `${one.label} ${one.count ?? ''}`);
    await openFilter(canvasElement, 'state', 'State');
    const before = counts();
    await expect(before).toEqual([
      'Waiting on you 1',
      'Working 2',
      'Idle 7',
      'Ended 1',
      'State not published 1',
    ]);
    await poll({ bIdle: true });
    await expect(shell.runtime.store.getSnapshot().acceptedCount).toBeGreaterThan(1);
    await expect(shell.display.hasPending()).toBe(true);
    await expect(counts()).toEqual(before);
    await expect(
      canvasElement.querySelector(
        `[data-next-operation-group="active"] [data-next-session="${SIDS.B}"]`,
      ),
    ).not.toBeNull();
    let painted = 0;
    const stop = shell.display.subscribe(() => {
      painted += 1;
    });
    try {
      await closeFilters();
      await waitFor(() =>
        expect(counts()).toEqual([
          'Waiting on you 1',
          'Working 1',
          'Idle 8',
          'Ended 1',
          'State not published 1',
        ]),
      );
      await expect(painted).toBe(1);
      await expect(shell.display.hasPending()).toBe(false);
      await expect(
        canvasElement.querySelector(
          `[data-next-operation-group="history"] [data-next-session="${SIDS.B}"]`,
        ),
      ).not.toBeNull();
    } finally {
      stop();
    }
  },
};

/* 17 */
export const FocusKeepsItsPlace: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const { shell } = current();
    const titleLink = () =>
      within(rowOf(canvasElement, 'B') as HTMLElement).getByRole('link', {
        name: 'Open session Changelog for 2.4',
      });
    // A row that moves between groups on a poll keeps focus on its link, by the row's key.
    const before = titleLink();
    before.focus();
    await poll({ bIdle: true });
    await waitFor(() =>
      expect(
        canvasElement.querySelector(
          `[data-next-operation-group="history"] [data-next-session="${SIDS.B}"]`,
        ),
      ).not.toBeNull(),
    );
    await waitFor(() => expect(titleLink()).toHaveFocus());
    await expect(titleLink()).not.toBe(before);
    // Each option keeps its place by <facet>:<value>.
    const state = await openFilter(canvasElement, 'state', 'State');
    await pick(state, 'Idle');
    await waitFor(() => expect(shownRows(canvasElement)).not.toContain('C'));
    (document.activeElement as HTMLElement | null)?.blur();
    await expect(shell.controls.focusLane.focus('state:Idle')).toBe(true);
    await expect(options(state, 'state').find((one) => one.label === 'Idle')?.box).toHaveFocus();
    await closeFilters();
    await waitFor(() => expect(trigger(canvasElement, 'State')).toHaveFocus());
    // A focused row link that leaves the filtered set hands focus to the search field.
    await waitFor(() => expect(shownRows(canvasElement)).toContain('B'));
    titleLink().focus();
    await poll({ bIdle: false });
    await waitFor(() => expect(shownRows(canvasElement)).not.toContain('B'));
    await waitFor(() =>
      expect(canvas.getByRole('searchbox', { name: 'Search sessions' })).toHaveFocus(),
    );
  },
};
