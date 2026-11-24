import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { contrastOf, paintedColors, paintedControlColors } from './a11y.audit';
import { auditCalm } from './calm.audit';
import { act, useEffect, useState } from 'react';
import { App } from '../src/App';
import { SESSION_LIST_WORDS, SESSION_ROW_WORDS } from '../src/language/glossary';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import type { Shell } from '../src/shell/context';
import { createFakeClock, createFakeEnvironment, type FakeClock } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { GENERATED as GLANCE_GENERATED, worthALookBoard } from '../test/worthALookBoard';
import { openInFlow } from './disclosure.flow';
import {
  GENERATED,
  SIDS,
  sessionRows,
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
    flagPoll?: boolean;
  };
}

let rig: Rig | null = null;
const current = (): Rig => {
  if (!rig) throw new Error('The board has not mounted.');
  return rig;
};

function glanceBoard(generated: number, links: boolean) {
  const board = worthALookBoard();
  const titles: Record<string, string> = {
    gate: 'Fix the flaky sign-in test',
    loop: 'Review pull request #482',
    'dirty-end': 'Nightly dependency check',
    'clean-end': 'Clean up old branches',
    'drift-none': 'Update the release checklist',
  };
  const sessions = board.sessions
    .filter(({ sid }) => sid in titles || (links && sid.startsWith('shared-')))
    .map((row) => ({ ...row, title: titles[row.sid] ?? row.title }));
  return {
    ...board,
    generated,
    ask: links,
    asks: links ? board.asks.filter(({ session_id }) => session_id === 'gate') : [],
    sessions: [
      ...sessions,
      {
        sid: 'onboarding',
        title:
          generated === GLANCE_GENERATED
            ? 'Write the onboarding guide'
            : 'Update the onboarding guide',
        project: 'onboarding',
        harness: 'claude',
        state: 'working',
      },
    ],
  };
}

const limitedBoard = {
  harnesses: [{ key: 'droid', label: 'Droid', discovered: true, error: 'Store unavailable' }],
  sessions: [
    {
      sid: 'deploy',
      project: 'ops',
      harness: 'claude',
      state: 'needs_input',
      state_detail: 'Approve production?',
    },
    {
      sid: 'docs',
      project: 'manual',
      harness: 'claude',
      state: 'needs_input',
      title: 'Edit handbook',
      state_detail: 'Choose chapter?',
    },
    { sid: 'scan', project: 'manual', harness: 'gemini', state: 'idle', acquisition: 'scan-only' },
  ],
};

function Board({
  annotate = true,
  showAll = false,
  rowExamples = false,
  auditPayload = false,
  goalEvidence = false,
  flagBoard,
  hash = '#n=sessions',
}: {
  readonly annotate?: boolean;
  readonly showAll?: boolean;
  readonly rowExamples?: boolean;
  readonly auditPayload?: boolean;
  readonly goalEvidence?: boolean;
  readonly flagBoard?:
    | 'mixed'
    | 'empty'
    | 'failed'
    | 'future-end'
    | 'glance'
    | 'links'
    | 'limited'
    | 'codex';
  readonly hash?: string;
}) {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment(hash);
    const clock =
      flagBoard === 'glance' || flagBoard === 'links'
        ? createFakeClock(new Date(2026, 10, 22, flagBoard === 'links' ? 15 : 11).getTime())
        : createFakeClock();
    const live: Rig['live'] = {
      generated: flagBoard === 'glance' || flagBoard === 'links' ? GLANCE_GENERATED : GENERATED,
      annotate,
      showAll,
      rowExamples,
      auditPayload,
      bWaiting: auditPayload,
    };
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
          url.startsWith('/api/data')
            ? json(
                flagBoard === 'codex'
                  ? {
                      generated: GENERATED,
                      annotate: true,
                      sessions: [{ harness: 'codex', sid: 'only', annotation_goal: 'Write docs' }],
                    }
                  : flagBoard === 'mixed'
                    ? worthALookBoard()
                    : flagBoard === 'limited'
                      ? limitedBoard
                      : flagBoard === 'empty'
                        ? {
                            sessions:
                              live.flagPoll || live.generated !== GENERATED
                                ? worthALookBoard().sessions.filter(
                                    ({ sid }) => sid === (live.flagPoll ? 'clean-end' : 'gate'),
                                  )
                                : [],
                          }
                        : flagBoard === 'failed'
                          ? {
                              sessions: [],
                              harnesses: [
                                {
                                  key: 'claude',
                                  label: 'Claude Code',
                                  discovered: true,
                                  error: 'Read failed',
                                },
                              ],
                            }
                          : flagBoard === 'future-end'
                            ? {
                                generated: GENERATED,
                                sessions: [
                                  {
                                    harness: 'claude',
                                    sid: 'future',
                                    title: 'Future-dated end',
                                    project: 'p',
                                    ended_at: GENERATED + 60,
                                  },
                                  {
                                    harness: 'claude',
                                    sid: 'recent',
                                    title: 'Recently ended',
                                    project: 'p',
                                    ended_at: GENERATED - 60,
                                  },
                                ],
                              }
                            : flagBoard === 'glance' || flagBoard === 'links'
                              ? glanceBoard(live.generated, flagBoard === 'links')
                              : goalEvidence
                                ? {
                                    ...sessionsSearchPayload(live),
                                    sessions: sessionRows(live).map((row) =>
                                      row['sid'] === SIDS.F
                                        ? {
                                            ...row,
                                            annotation_goal: '',
                                            annotation_goal_why: 'No goal typed for this session.',
                                          }
                                        : row,
                                    ),
                                  }
                                : sessionsSearchPayload(live),
              )
            : json({}),
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

export const ReportedEndWithoutAge: Story = {
  args: { flagBoard: 'future-end' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const future = (
      await canvas.findByRole('link', { name: 'Open session Future-dated end' })
    ).closest('article');
    if (!future) throw new Error('Missing the future-dated end row');
    const row = within(future);
    await expect(row.getByRole('img', { name: 'Ended' })).toBeVisible();
    await expect(row.getByText('Session reported its own end')).toBeVisible();
    await expect(row.queryByText(/ended \d+ .* ago/)).toBeNull();
    await expect(canvas.getByText('ended 1 minute ago')).toBeVisible();
  },
};

export const SessionsAtAGlance: Story = {
  args: { flagBoard: 'glance' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = await canvas.findByRole('heading', { level: 1, name: 'Good morning' });
    const summary = canvas.getByText(
      'You have 1 waiting on you, 2 working, 1 quiet and 2 ended on this board.',
    );
    await expect(heading.parentElement?.querySelectorAll('p')).toHaveLength(1);
    await expect(summary).toBeVisible();
    const region = canvas.getByRole('region', { name: 'At a glance' });
    const glance = within(region);
    const waiting = glance.getByRole('link', { name: /^Waiting on you 1 .*Open in Needs you$/ });
    const working = glance.getByRole('button', {
      name: /^Working now 2 .*Show in the list below$/,
    });
    const worth = glance.getByRole('link', { name: /^Worth a look 2 .*Open in Needs you$/ });
    await expect([...region.children]).toEqual([waiting, working, worth]);
    for (const label of [heading, summary, ...region.querySelectorAll('span, strong')]) {
      const style = getComputedStyle(label);
      await expect(style.fontFamily).toMatch(/Inter/);
      await expect(style.fontFamily).not.toMatch(/monospace/i);
      await expect(style.textTransform).toBe('none');
    }
    current().clock.advance(2 * 60 * 60 * 1000);
    await poll();
    await expect(
      await canvas.findByRole('heading', { name: 'Good afternoon', level: 1 }),
    ).toBeVisible();
    await expect(glance.getByText('Update the onboarding guide')).toBeVisible();
  },
};

export const SessionsReportsLimitedCoverage: Story = {
  args: { flagBoard: 'limited' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const region = await canvas.findByRole('region', { name: 'At a glance' });
    const summary =
      'You have 2 waiting on you, 0 working, 0 quiet, 0 ended and 1 with limited state evidence among the sessions Compass could read, with some sources unavailable.';
    await expect(canvas.getByText(summary)).toBeVisible();
    await expect(region).toHaveAccessibleDescription(summary);
    const card = within(within(region).getByRole('link', { name: /Waiting on you 2/ }));
    const deploy = card.getByText('Approve production?').parentElement;
    const handbook = card.getByText('Choose chapter?').parentElement;
    await expect(deploy).toHaveTextContent('Title not published');
    await expect(deploy).not.toHaveTextContent('Edit handbook');
    await expect(handbook).toHaveTextContent('Edit handbook');
  },
};

export const AtAGlanceLinksAndWorkingFilter: Story = {
  args: { flagBoard: 'links' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const cards = () => within(canvas.getByRole('region', { name: 'At a glance' }));
    await canvas.findByRole('region', { name: 'At a glance' });
    const waiting = cards().getByRole('link', { name: /Waiting on you 1/ });
    const working = cards().getByRole('button', { name: /Working now 2/ });
    const worth = cards().getByRole('link', { name: /Worth a look 4/ });
    if ('__vitest_browser_runner__' in window) {
      const { page, userEvent: keyboard } = await import('vitest/browser');
      const edge = (card: HTMLElement) => {
        const style = getComputedStyle(card);
        return [style.borderTopColor, style.boxShadow];
      };
      const heading = page.getByRole('heading', { name: 'Good afternoon' });
      const region = page.getByRole('region', { name: 'At a glance' });
      await heading.hover();
      const resting = edge(waiting);
      await region.getByRole('link', { name: /Waiting on you 1/ }).hover();
      const hovered = edge(waiting);
      await expect(hovered[0]).not.toBe(resting[0]);
      await expect(hovered[1]).not.toBe('none');
      await region.getByRole('button', { name: /Working now 2/ }).hover();
      await expect(edge(working)).toEqual(hovered);
      await region.getByRole('link', { name: /Worth a look 4/ }).hover();
      await expect(edge(worth)).toEqual(hovered);
      await heading.hover();

      for (
        let step = 0;
        step < 12 && canvasElement.ownerDocument.activeElement !== waiting;
        step += 1
      ) {
        await keyboard.tab();
      }
      await expect(waiting).toHaveFocus();
      const outline = getComputedStyle(waiting).outline;
      await expect(getComputedStyle(waiting).outlineWidth).not.toBe('0px');
      for (const card of [working, worth]) {
        await keyboard.tab();
        await expect(card).toHaveFocus();
        await expect(getComputedStyle(card).outline).toBe(outline);
      }
    }
    for (const [label, section, identities] of [
      [/Waiting on you 1/, 'needs', ['gate']],
      [/Worth a look 4/, 'risk', ['dirty-end', 'loop', 'shared-one', 'shared-two']],
    ] as const) {
      await userEvent.click(cards().getByRole('link', { name: label }));
      await expect(
        await canvas.findByRole('heading', { name: 'Needs you', level: 1 }),
      ).toBeVisible();
      const queue = canvasElement.querySelector(`[data-next-attention-section="${section}"] > ol`);
      if (!queue) throw new Error(`Missing ${section} section`);
      const rows = [...queue.querySelectorAll<HTMLElement>('article[data-next-subject-key]')];
      await expect(
        rows
          .map(
            (row) => JSON.parse(row.dataset['nextSubjectKey']?.slice('session:'.length) ?? '[]')[1],
          )
          .sort(),
      ).toEqual([...identities]);
      if (section === 'needs') {
        await expect(rows[0]).toHaveTextContent('Waiting for you to approve a command');
        await expect(rows[0]).toHaveTextContent('Approve?');
        const wrap = canvasElement.querySelector('[data-next-attention-section="close"]');
        await expect(wrap).toHaveTextContent('Ready to wrap up (1)');
        await expect(wrap?.querySelector('[data-next-subject-key]')).toHaveAttribute(
          'data-next-subject-key',
          'session:["claude","clean-end"]',
        );
      } else {
        await expect(canvasElement.querySelector('[data-next-board-risk="collision"]')).toBeNull();
        for (const row of rows.filter((row) =>
          row.dataset['nextSubjectKey']?.includes('shared-'),
        )) {
          await expect(row).toHaveTextContent('Shared project label');
        }
        await expect(
          rows.find((row) => row.dataset['nextSubjectKey']?.includes('dirty-end')),
        ).toHaveTextContent('uncommitted');
      }
      const { history } = current();
      history.back();
      history.flush();
      await canvas.findByRole('region', { name: 'At a glance' });
    }
    const status = within(canvas.getByRole('group', { name: 'Session status' }));
    const waitingTab = status.getByRole('button', { name: 'Waiting on you 1' });
    await userEvent.click(waitingTab);
    const waitingRows = within(canvas.getByRole('region', { name: 'All sessions' }));
    await waitFor(() =>
      expect(waitingRows.getAllByRole('link', { name: /^Open session / })).toHaveLength(1),
    );
    await expect(
      waitingRows.getByRole('link', { name: 'Open session Fix the flaky sign-in test' }),
    ).toBeVisible();
    const button = cards().getByRole('button', { name: /Working now 2/ });
    const list = canvas.getByRole('region', { name: 'All sessions' });
    const rows = () => within(list).getAllByRole('link', { name: /^Open session / });
    await expect(button).toHaveAttribute('aria-controls', list.id);
    await expect(waitingTab).toHaveAttribute('aria-pressed', 'true');
    const search = canvas.getByRole('searchbox', { name: 'Search sessions' });
    await userEvent.type(search, 'onboarding');
    await userEvent.click(button);
    await expect(search).toHaveValue('onboarding');
    await expect(waitingTab).toHaveAttribute('aria-pressed', 'false');
    await waitFor(async () => {
      await expect(list).toHaveFocus();
      await expect(rows()).toHaveLength(1);
      await expect(rows()[0]).toHaveAccessibleName('Open session Write the onboarding guide');
    });
    await expect(list.getBoundingClientRect().top).toBeGreaterThanOrEqual(0);
    await expect(list.getBoundingClientRect().top).toBeLessThan(window.innerHeight);
    await userEvent.clear(search);
    await waitFor(async () => await expect(rows()).toHaveLength(2));
    await poll();
    await expect(
      await within(list).findByRole('link', { name: 'Open session Update the onboarding guide' }),
    ).toBeVisible();
    await expect(rows()).toHaveLength(2);
    await userEvent.click(
      within(list).getByRole('link', { name: 'Open session Review pull request #482' }),
    );
    await expect(
      await canvas.findByRole('heading', { name: 'Review pull request #482', level: 1 }),
    ).toBeVisible();
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard('{Escape}');
    await waitFor(async () => {
      await expect(cards().getByRole('button', { name: /Working now 2/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(
        within(canvas.getByRole('region', { name: 'All sessions' })).getAllByRole('link', {
          name: /^Open session /,
        }),
      ).toHaveLength(2);
    });
  },
};

export const WorkingCanBeClearedOnAnEmptyBoard: Story = {
  args: { flagBoard: 'empty' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const working = await canvas.findByRole('button', { name: /Working now 0/ });
    await userEvent.click(working);
    await expect(working).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(working);
    await expect(working).toHaveAttribute('aria-pressed', 'false');
    await poll();
    const list = within(canvas.getByRole('region', { name: 'All sessions' }));
    await expect(await list.findByRole('link', { name: 'Open session gate' })).toBeVisible();
  },
};

export const WorthALook: Story = {
  args: { flagBoard: 'mixed' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole('button', { name: 'Worth a look 9' });
    const dirty = canvas.getByRole('link', { name: 'Open session dirty-end' }).closest('article');
    if (!dirty) throw new Error('Missing the ended row');
    const tile = within(dirty).getByRole('img', { name: 'Ended' });
    const flag = within(dirty)
      .getByText('Worth a look: Ended with uncommitted work (2 changed entries)')
      .closest('[data-next-row-worth-a-look]');
    if (!flag) throw new Error('Missing the flag line');
    await expect(tile).toBeVisible();
    await expect(flag).toBeVisible();
    const glyph = flag.querySelector('svg[data-icon="worth-a-look"]');
    if (!glyph) throw new Error('Missing the warning glyph');
    await expect(glyph).toBeVisible();
    for (const width of [1280, 390]) {
      await atWidth(width, async () => {
        const box = glyph.getBoundingClientRect();
        const css = getComputedStyle(glyph);
        await expect(Math.abs(box.width - box.height)).toBeLessThan(0.2);
        await expect(css.flexShrink).toBe('0');
        await expect(parseFloat(css.top)).toBeGreaterThan(0);
      });
    }
    await expect(dirty.querySelectorAll('svg[data-icon="worth-a-look"]')).toHaveLength(1);
    for (const line of canvasElement.querySelectorAll('[data-next-row-worth-a-look]')) {
      const colors = paintedColors(line);
      if (!colors) throw new Error('Missing painted colours for the flag');
      await expect(contrastOf(colors.foreground, colors.background)).toBeGreaterThanOrEqual(4.5);
    }
    const state = await openFilter(canvasElement, 'state');
    await expect(within(state).queryByText('Worth a look', { exact: true })).toBeNull();
    await userEvent.keyboard('{Escape}');
    for (const name of ['drift-high', 'gate', 'clean-end']) {
      await expect(canvas.getByRole('link', { name: `Open session ${name}` })).toBeVisible();
    }
    await expect(canvas.queryByRole('button', { name: 'Off course' })).toBeNull();
    await userEvent.click(toggle);
    const rows = () => canvasElement.querySelectorAll('article.next-operation-row');
    await waitFor(() => expect(rows()).toHaveLength(9));
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    for (const name of ['drift-high', 'gate', 'clean-end']) {
      await expect(canvas.queryByRole('link', { name: `Open session ${name}` })).toBeNull();
    }
    await userEvent.click(canvas.getByRole('button', { name: 'All 18' }));
    await waitFor(() => expect(rows()).toHaveLength(18));
  },
};

export const WorthALookEmptyBoard: Story = {
  args: { flagBoard: 'empty' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole('button', { name: 'Worth a look 0' });
    await expect(toggle).toBeVisible();
    await expect(toggle).toBeDisabled();
    await userEvent.click(toggle);
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await expect(canvasElement.querySelector('[data-next-row-worth-a-look]')).toBeNull();
    await expect(canvas.getByText('No recent-history rows in this payload.')).toBeVisible();
    await poll({ flagPoll: true });
    await expect(await canvas.findByRole('link', { name: 'Open session clean-end' })).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  },
};

export const WorthALookUnreadBoard: Story = {
  args: { flagBoard: 'failed' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole('button', { name: 'Worth a look unavailable' }),
    ).toBeDisabled();
    await expect(canvas.getByText(/Claude Code: Harness source could not be read/)).toBeVisible();
    await expect(canvas.queryByRole('button', { name: 'Worth a look 0' })).toBeNull();
    await expect(canvasElement.querySelectorAll('[data-sessions-group-count]')).toHaveLength(0);
    const state = await openFilter(canvasElement, 'state');
    await waitFor(() => expect(within(state).getByText('Working', { exact: true })).toBeVisible());
    await expect(state.querySelectorAll('[data-filter-count]')).toHaveLength(0);
    await closeFilters(canvasElement);
    await userEvent.type(canvas.getByRole('searchbox'), 'quarterly invoices');
    await expect(
      await canvas.findByText(
        'Search results are unavailable because the sources could not be read.',
      ),
    ).toBeVisible();
    await expect(canvas.queryByText('Nothing here matches.')).toBeNull();
  },
};

export const StatusLegend: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const legend = within(canvasElement).getByRole('list', { name: 'What the icons mean' });
    const entries = [
      ['Working', 'working'],
      ['Waiting on you', 'waiting'],
      ['Quiet', 'quiet'],
      ['Ended', 'ended'],
      ['State not known', 'state-not-known'],
      ['Worth a look', 'worth-a-look'],
    ];
    await expect(within(legend).getAllByRole('listitem')).toHaveLength(entries.length);
    for (const [word, icon] of entries) {
      const label = within(legend).getByText(word ?? '', { exact: true });
      await expect(label).toBeVisible();
      await expect(label.closest('li')?.querySelector(`svg[data-icon="${icon}"]`)).toBeVisible();
    }
    const canvas = within(canvasElement);
    for (const [id, name] of [
      ['A', 'Waiting on you'],
      ['B', 'Working'],
      ['D', 'Quiet'],
      ['E', 'Ended'],
    ] as const) {
      const row = rowOf(canvasElement, id);
      if (!row) throw new Error(`Missing row ${id}`);
      const tile = within(row).getByRole('img', { name });
      await expect(within(row).getAllByRole('img')).toHaveLength(1);
      await expect(tile).toBeVisible();
      const { width, height } = tile.getBoundingClientRect();
      await expect(width).toBeGreaterThanOrEqual(44);
      await expect(height).toBeGreaterThanOrEqual(44);
      const css = getComputedStyle(tile);
      await expect(css.fontFamily).toContain('Inter');
      await expect(css.textTransform).toBe('none');
      await expect(tile.textContent).toBe('');
      const glyph = tile.querySelector('svg');
      if (!glyph) throw new Error(`Missing glyph for ${name}`);
      const artwork = getComputedStyle(glyph.parentElement as HTMLElement);
      await expect([artwork.width, artwork.height, artwork.borderRadius]).toEqual([
        '40px',
        '40px',
        '12px',
      ]);
      const colors = paintedColors(glyph);
      if (!colors) throw new Error(`Missing painted colours for ${name}`);
      await expect(contrastOf(colors.foreground, colors.background)).toBeGreaterThanOrEqual(3);
      if (name === 'Quiet') {
        // The leading path of Phosphor Moon Bold, including its 12px corner arcs.
        await expect(glyph.querySelector('path')?.getAttribute('d')).toMatch(
          /^M236\.37,139\.4a12,12,0,0,0-12-3A84\.07,84\.07/,
        );
      }
    }
    for (const word of ['Finished', 'Paused', 'Idle']) {
      await expect(canvas.queryByText(word, { exact: true })).toBeNull();
      await expect(canvas.queryByRole('img', { name: word })).toBeNull();
    }
    const first = rowOf(canvasElement, 'A');
    if (!first) throw new Error('Missing first row');
    const waiting = within(first).getByRole('img', { name: 'Waiting on you' });
    await userEvent.click(waiting);
    await userEvent.tab({ shift: true });
    await userEvent.tab();
    await expect(waiting).toHaveFocus();
    const tooltip = await within(document.body).findByRole('tooltip');
    await expect(tooltip).toHaveTextContent(/^Waiting on you$/);
    await userEvent.keyboard('{Escape}');
    const scan = rowOf(canvasElement, 'F')?.querySelector('[data-next-row-state]');
    await expect(scan).toBeVisible();
    await expect(scan).toHaveTextContent('Read by scanning: no turn end can be observed here');
    await expect(scan?.querySelector('svg')).toBeNull();
    const live = rowOf(canvasElement, 'B')?.querySelector(
      '[data-next-row-state] [data-icon="working"]',
    );
    const lapsed = rowOf(canvasElement, 'C')?.querySelector(
      '[data-next-row-state] [data-icon="working"]',
    );
    if (!live || !lapsed) throw new Error('Expected both Working shapes');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    await expect(getComputedStyle(live).animationName).toBe(
      reduced ? 'none' : 'next-status-tile-pulse',
    );
    await expect(getComputedStyle(lapsed).animationName).toBe('none');
    const unknown = rowOf(canvasElement, 'J')?.querySelector('[data-next-row-state]');
    await expect(unknown).toHaveTextContent('State not published');
    await expect(unknown?.querySelector('svg')).toBeNull();
    // Both rows still draw a tile: the neutral State not known one (owner, 2026-11-24).
    for (const id of ['F', 'J'] as const) {
      const row = rowOf(canvasElement, id);
      if (!row) throw new Error(`Missing row ${id}`);
      await expect(within(row).getByRole('img', { name: 'State not known' })).toBeVisible();
    }
    await expect(canvas.getByRole('status', { name: 'Working sessions' })).toHaveTextContent(
      '2 sessions working',
    );
  },
};

export const StatusTilesWithoutProgress: Story = {
  args: { rowExamples: true },
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    for (const [id, state] of [
      ['D', 'Quiet'],
      ['E', 'Ended'],
    ] as const) {
      const row = rowOf(canvasElement, id);
      if (!row) throw new Error(`Missing row ${id}`);
      const reads = within(row);
      const tile = reads.getByRole('img', { name: state });
      const title = reads.getByRole('link', { name: /^Open session/ });
      await expect(tile.getBoundingClientRect().right).toBeLessThanOrEqual(
        title.getBoundingClientRect().left,
      );
    }
    for (const id of ['B', 'C', 'D', 'E', 'K'] as const) {
      const row = rowOf(canvasElement, id);
      if (!row) throw new Error(`Missing row ${id}`);
      await expect(
        row.querySelector('.next-operation-progress, [data-variant="progress"]'),
      ).toBeNull();
      await expect(row).not.toHaveTextContent(/No goal yet|Not checked yet/);
    }
    await atWidth(1200, async () => {
      const active = rowOf(canvasElement, 'B');
      const history = canvasElement.querySelector('[data-next-operation-history]');
      if (!active || !history) throw new Error('Missing desktop session rows');
      // The session beside its goal; the Project, Next and Blocked columns are gone.
      await expect(getComputedStyle(active).gridTemplateColumns.split(' ')).toHaveLength(2);
      await expect(getComputedStyle(history).gridTemplateColumns.split(' ')).toHaveLength(2);
    });
  },
};

export const AssignmentAndLocation: Story = {
  args: { rowExamples: true },
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const row = rowOf(canvasElement, 'B');
    if (!row) throw new Error('Missing Changelog row');
    const detail = within(row).getByText('Fix queue');
    await expect(detail).toHaveAttribute('data-authored');
    const title = within(row).getByText('Changelog for 2.4');
    const goal = within(row).getByText('Ship the 2.4 changelog');
    await expect(title).toHaveAttribute('data-authored');
    await expect(goal).toHaveAttribute('data-authored');
    const assignment = detail.parentElement;
    if (!assignment) throw new Error('Missing current task line');
    const location = within(row).getByText(/share this display label across/);
    await expect(assignment.parentElement?.innerText).toContain(
      `${assignment.textContent}\n${location.textContent}`,
    );
    await expect(location.getBoundingClientRect().top).toBeGreaterThanOrEqual(
      assignment.getBoundingClientRect().bottom,
    );
    const excerpts = [title, goal, detail];
    const originals = excerpts.map((node) => node.textContent);
    try {
      excerpts.forEach((node) => {
        node.textContent = 'Revisit 1795327749000 and 1f4b8cd9 [3]';
      });
      await expect(auditCalm(canvasElement)).toEqual([]);
    } finally {
      excerpts.forEach((node, index) => {
        node.textContent = originals[index] ?? '';
      });
    }
  },
};

export const ProjectActivityIcons: Story = {
  args: { hash: '#n=project:recce%2Fcompass' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const sessions = within(await canvas.findByRole('region', { name: 'Sessions' }));
    const currentRun = within(await sessions.findByRole('link', { name: /Changelog for 2.4/ }));
    await expect(currentRun.getByRole('img', { name: 'Working' })).toBeVisible();
    const ended = within(await sessions.findByRole('link', { name: /Theme tokens/ }));
    await expect(ended.getByRole('img', { name: 'Ended' })).toBeVisible();
  },
};

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
  root.querySelector(`[data-next-operation-group="${kind}"] > header h2`)?.textContent ?? '';
const cue = (root: HTMLElement) => root.querySelector('#next-cockpit-cue-status') as HTMLElement;
const ACTIVE_HEADER = 'Right now';
const HISTORY_HEADER = 'Earlier in the last 24 hours';

async function ready(root: HTMLElement) {
  const canvas = within(root);
  await canvas.findByRole('search', { name: 'Find sessions' });
  await waitFor(() => expect(shownRows(root)).toHaveLength(12));
  return canvas;
}

const filtersButton = (root: HTMLElement) => within(root).getByRole('button', { name: 'Filters' });

async function openPanel(root: HTMLElement) {
  const button = filtersButton(root);
  if (button.getAttribute('aria-expanded') !== 'true') await userEvent.click(button);
  return within(root).getByRole('region', { name: 'Filters' });
}

async function openFilter(root: HTMLElement, facet: string) {
  const panel = await openPanel(root);
  const more = within(panel).getByRole('button', { name: 'More filters for power users' });
  if (more.getAttribute('aria-expanded') !== 'true') await userEvent.click(more);
  const section = panel.querySelector<HTMLElement>(`[data-filter-facet="${facet}"]`);
  if (!section) throw new Error(`Missing ${facet} facet`);
  return section;
}

async function closeFilters(root: HTMLElement) {
  const button = filtersButton(root);
  if (button.getAttribute('aria-expanded') === 'true') await userEvent.click(button);
}

async function startedToday(root: HTMLElement) {
  const panel = await openPanel(root);
  return within(within(panel).getByRole('group', { name: 'Started' })).getByRole('button', {
    name: 'Today',
  });
}

const options = (popup: HTMLElement, facet: string) =>
  [...popup.querySelectorAll<HTMLElement>(`[data-filter-option^="${facet}:"]`)].map((row) => ({
    label: row.querySelector('[data-filter-label]')?.textContent ?? '',
    count: row.querySelector('[data-filter-count]')?.textContent ?? null,
    note: row.querySelector('[data-filter-note]')?.textContent ?? '',
    box: row.querySelector<HTMLElement>('[role=checkbox], [role=radio]'),
  }));

async function pick(popup: HTMLElement, label: string) {
  await userEvent.click(
    within(popup).getByText(label, {
      exact: true,
      selector: '[data-filter-label], [data-filter-option^="date-field:"] span:last-child',
    }),
  );
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

export const HeadlessSubsets: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const popup = await openFilter(canvasElement, 'headless');
    await expect(options(popup, 'headless').map(({ label, count }) => ({ label, count }))).toEqual([
      { label: 'Headless', count: '1' },
      { label: 'Interactive or unknown', count: '11' },
    ]);
    await waitFor(() =>
      expect(
        within(popup).getByText(
          'Read from Claude Code transcripts and Codex rollout metadata. Interactive or unknown includes unknown entrypoints and other harnesses.',
        ),
      ).toBeVisible(),
    );
    await pick(popup, 'Interactive or unknown');
    await closeFilters(canvasElement);
    await waitFor(() => expect(shownRows(canvasElement)).toBe('ACDEFGHIJKL'));
    await expect(rowOf(canvasElement, 'A')).not.toBeNull();
    await expect(rowOf(canvasElement, 'B')).toBeNull();
    await expect(rowOf(canvasElement, 'C')).not.toBeNull();
    await expect(chips(canvasElement)).toEqual(['Headless: Interactive or unknown']);
    await poll();
    await waitFor(() => expect(shownRows(canvasElement)).toBe('ACDEFGHIJKL'));
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Clear all' }));
    await waitFor(() => expect(shownRows(canvasElement)).toBe('ABCDEFGHIJKL'));
    const headlessPopup = await openFilter(canvasElement, 'headless');
    await pick(headlessPopup, 'Headless');
    await closeFilters(canvasElement);
    await waitFor(() => expect(shownRows(canvasElement)).toBe('B'));
    await expect(rowOf(canvasElement, 'B')).not.toBeNull();
    await expect(rowOf(canvasElement, 'A')).toBeNull();
    await expect(rowOf(canvasElement, 'C')).toBeNull();
    await expect(chips(canvasElement)).toEqual(['Headless: Headless']);
  },
};

/* 1 */
export const ExplanationsOpenInPlace: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    await openFilter(canvasElement, 'state');
    const counts = canvas.getByRole('button', { name: 'How filter counts work' });
    await openInFlow(counts, canvas.getByRole('heading', { name: 'Right now' }));
    const history = canvas.getByRole('button', { name: 'How session history works' });
    const rows = canvasElement.querySelector<HTMLElement>(
      '[data-next-operation-group="history"] .next-operation-rows',
    );
    if (!rows) throw new Error('The earlier session rows did not render');
    await openInFlow(history, rows);
    await poll();
    await expect(counts).toHaveAttribute('aria-expanded', 'true');
    await expect(history).toHaveAttribute('aria-expanded', 'true');
  },
};

export const AllHistoryNamesTheScope: Story = {
  args: { showAll: true, annotate: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('heading', { name: 'Earlier sessions' })).toBeVisible();
    await expect(canvasElement.querySelector('[data-next-session="6a7b8c9d0e1f"]')).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'How session history works' }));
    await waitFor(() =>
      expect(canvas.getByText(/Annotations are off, so goals cannot be typed/)).toBeVisible(),
    );
  },
};

export const FiltersStayOpenWhileChoosing: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const project = await openFilter(canvasElement, 'project');
    const panel = within(canvasElement).getByRole('region', { name: 'Filters' });
    const date = await openFilter(canvasElement, 'date');
    await waitFor(() => expect(project.querySelector('[data-filter-label]')).toBeVisible());
    await expect(date.querySelector('[data-filter-label]')).toBeVisible();
    await expect(panel.closest('[data-slot="popover-content"]')).toBeNull();
    const rightNow = within(canvasElement).getByRole('heading', { name: 'Right now' });
    await expect(panel.getBoundingClientRect().bottom).toBeLessThan(
      rightNow.getBoundingClientRect().top,
    );
  },
};

export const CompassLabelsAndPayloadWordsCoexist: Story = {
  args: { auditPayload: true },
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const glance = canvas.getByRole('region', { name: 'At a glance' });
    for (const words of [
      'Approve deadbeef at 1795327749000 [3]?',
      'Decision on branch deadbeef [11]',
    ]) {
      await expect(glance).toHaveTextContent(words);
      await expect(
        canvasElement.querySelector('[data-next-operation-group="active"]'),
      ).toHaveTextContent(words);
    }
    const row = canvas
      .getByRole('link', { name: 'Open session Parser cleanup' })
      .closest('article');
    for (const words of ['Review deadbeef [4]', 'project [6]', 'worktree branch [7]']) {
      await expect(row).toHaveTextContent(words);
    }
    // The pending step was the Next column, which the row no longer has; the session page keeps it.
    await expect(row).not.toHaveTextContent('Ship deadbeef [5]');
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

export const DefaultBoard: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const page = canvasElement.ownerDocument;
    await expect(page.documentElement).toHaveStyle({ colorScheme: 'light' });
    await expect(page.body).toHaveStyle({ backgroundColor: 'rgb(244, 246, 248)' });
    await expect(getComputedStyle(page.body).fontFamily).toMatch(/^Inter,/);
    await page.fonts.ready;
    await expect(page.fonts.check('15px Inter', 'Sessions')).toBe(true);
    await expect(
      [...page.fonts].some((face) => face.family === 'Inter' && face.status === 'loaded'),
    ).toBe(true);
    const search = canvas.getByRole('search', { name: 'Find sessions' });
    const glance = canvas.getByRole('region', { name: 'At a glance' });
    const active = canvas.getByRole('heading', { level: 2, name: 'Right now' });
    await expect(glance.compareDocumentPosition(search) & FOLLOWS).toBeTruthy();
    await expect(search.compareDocumentPosition(active) & FOLLOWS).toBeTruthy();
    await expect(chips(canvasElement)).toEqual([]);
    const rows = canvasElement.querySelectorAll('[data-next-operation-group]');
    // Rows follow the redesign canvas: no column header strip.
    await expect(rows[0]?.querySelector('.next-operations-columns')).toBeNull();
    await expect(auditCalm(canvasElement)).toEqual([]);
    await expect(canvas.getByRole('button', { name: 'All 12' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(filtersButton(canvasElement)).toHaveAttribute('aria-expanded', 'false');
    await expect(headerText(canvasElement, 'active')).toBe(ACTIVE_HEADER);
    await expect(headerText(canvasElement, 'history')).toBe(HISTORY_HEADER);
    await expect(shownLines(canvasElement)).toEqual([]);
    const cards = within(glance);
    await expect(cards.getByRole('link', { name: /Waiting on you 1/ })).toBeVisible();
    await expect(cards.getByRole('button', { name: /Working now 2/ })).toBeVisible();
  },
};

export const TitlesOpenSessions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const title = canvas.getAllByRole('link', { name: /^Open session / })[0] as HTMLElement;
    const example = canvas.getByRole('link', { name: 'See an example' });
    const decoration = (link: HTMLElement) => getComputedStyle(link).textDecorationLine;
    await expect(title).toHaveAttribute('href', expect.stringContaining('#'));
    await expect(decoration(title)).toBe('none');
    await expect(example.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    const invite = example.closest('[data-sample-invite]');
    await expect(invite).toHaveTextContent(
      'Open an example session to see how goals, progress checks and Steer back work.',
    );
    await expect(invite).toHaveStyle({
      backgroundColor: 'rgb(230, 242, 236)',
      borderLeftWidth: '1px',
    });
    // The row is the title's 44 px target (owner, 2026-11-24): the link covers the whole card, so the title's
    // own box can keep its line height and the descriptor sits directly under it.
    const row = title.closest('article') as HTMLElement;
    row.scrollIntoView({ block: 'center' });
    const box = row.getBoundingClientRect();
    await expect(box.height).toBeGreaterThanOrEqual(44);
    await expect(box.width).toBeGreaterThanOrEqual(44);
    await expect(document.elementFromPoint(box.left + 6, box.top + 6)).toBe(title);
    if ('__vitest_browser_runner__' in window) {
      const { page } = await import('vitest/browser');
      await page
        .getByRole('link', { name: /^Open session / })
        .first()
        .hover();
      await expect(decoration(title)).toBe('underline');
      await page.getByRole('searchbox', { name: 'Search sessions' }).hover();
      await expect(decoration(title)).toBe('none');
    }
    title.focus();
    await expect(title).toHaveFocus();
    await expect(decoration(title)).toBe('underline');
    await expect(title).toHaveStyle({
      outlineWidth: '2px',
      outlineStyle: 'solid',
      outlineColor: 'rgb(47, 125, 91)',
      outlineOffset: '2px',
    });
  },
};

/* 2 */
export const SearchByWords: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const glance = canvas.getByRole('region', { name: 'At a glance' });
    const before = glance.textContent;
    await userEvent.type(canvas.getByRole('searchbox', { name: 'Search sessions' }), 'release');
    await waitFor(() =>
      expect(resultText(canvasElement)).toBe(
        'Showing 2 of 12 sessions. At a glance counts the whole board.',
      ),
    );
    await expect(shownRows(canvasElement)).toBe('BK');
    await expect(shownLines(canvasElement)).toEqual(['1 of 4 shown', '1 of 8 shown']);
    const shown = canvasElement.querySelector('[data-next-sessions-shown="active"]') as HTMLElement;
    const clear = within(shown).getByRole('button', { name: 'Clear filters' });
    await expect(clear).toHaveStyle({
      borderColor: 'rgba(0, 0, 0, 0)',
      color: 'rgb(47, 125, 91)',
      textDecorationLine: 'none',
    });
    await expect(
      rowOf(canvasElement, 'B')?.querySelector('[data-next-row-hint]'),
    ).toHaveTextContent('Matched in your first prompt: "write the release notes for 2.4"');
    await expect(rowOf(canvasElement, 'K')?.querySelector('[data-next-row-hint]')).toBeNull();
    const guard = canvasElement.querySelector('[data-sessions-hidden-waiting]') as HTMLElement;
    await expect(guard).toHaveTextContent('1 session waiting on you is hidden by these filters.');
    await expect(
      within(guard).getByRole('link', { name: 'Open it: Combat Completion' }),
    ).toBeVisible();
    await expect(glance.textContent).toBe(before);
  },
};

/* 3 */
export const StartedTodayAndMissingStartTimes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const preset = await startedToday(canvasElement);
    await userEvent.click(preset);
    await expect(preset).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('ABEFK'));
    const date = filtersButton(canvasElement);
    await expect(chips(canvasElement)).toEqual(['Started: Today']);
    await expect(canvasElement.querySelector('[data-sessions-unstamped]')).toHaveTextContent(
      '4 sessions have no published start time and are not shown.',
    );
    const popup = await openFilter(canvasElement, 'date');
    await expect(popup.querySelector('[data-sessions-unstamped-harnesses]')).toHaveTextContent(
      'No start time is published for: Cursor, Goose, OpenCode, Pi.',
    );
    await closeFilters(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Include them' }));
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(9));
    // The button goes as it is pressed, and hands focus to the Date button rather than to the page.
    await expect(date).toHaveFocus();
    await expect(chips(canvasElement)).toEqual(['Started: Today, plus 4 with no start time']);
    const again = await openFilter(canvasElement, 'date');
    const unstamped = options(again, 'when').find((one) => one.label === 'Start not published');
    await expect(unstamped?.count).toBe('4');
    await pick(again, 'Start not published');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('GHIJ'));
    await pick(again, 'Last 7 days');
    await waitFor(() =>
      expect(rowOf(canvasElement, 'C')?.querySelector('[data-next-row-hint]')).toHaveTextContent(
        'Started yesterday, from the first message',
      ),
    );
  },
};

export const ClearingStartedResetsMissingTimes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const today = await startedToday(canvasElement);
    const panel = within(await openPanel(canvasElement));
    const week = within(panel.getByRole('group', { name: 'Started' })).getByRole('button', {
      name: 'Last 7 days',
    });
    for (const [selected, other] of [
      [today, week],
      [week, today],
    ] as const) {
      await userEvent.click(selected);
      await userEvent.click(canvas.getByRole('button', { name: 'Include them' }));
      await expect(chips(canvasElement)[0]).toContain('plus 4 with no start time');
      await userEvent.click(selected);
      await expect(chips(canvasElement)).toEqual([]);
      await userEvent.click(other);
      await expect(canvas.getByRole('button', { name: 'Include them' })).toBeVisible();
      await userEvent.click(other);
    }
  },
};

/* 4 */
export const DatesBeyondTheBoardWindow: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const popup = await openFilter(canvasElement, 'date');
    await pick(popup, 'Yesterday');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('CDL'));
    await closeFilters(canvasElement);
    const search = canvas.getByRole('search', { name: 'Find sessions' });
    const started = search.querySelector(':scope > [data-sessions-window-note="started"]');
    await expect(started).toHaveTextContent(
      'The board holds sessions active since 2030-01-14 12:00 (the last 24 hours). A session that started in this range and went quiet before then is not on the board.',
    );
    await userEvent.click(
      within(started as HTMLElement).getByRole('button', { name: 'Filter by last active instead' }),
    );
    await waitFor(() => expect(shownRows(canvasElement)).toBe('L'));
    await expect(filtersButton(canvasElement)).toHaveFocus();
    const note = search.querySelector(
      ':scope > [data-sessions-window-note="active"]',
    ) as HTMLElement;
    await expect(note).toHaveTextContent('Older sessions are not loaded.');
    const link = canvas.getByRole('link', { name: 'Show older sessions' });
    await expect(link.parentElement).toHaveTextContent('Your filters are not kept.');
    await expect(link.getAttribute('href')?.endsWith('?all=1#n=sessions')).toBe(true);
    await pick(await openFilter(canvasElement, 'date'), 'Today');
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(11));
    await expect(canvasElement.querySelector('[data-sessions-window-note]')).toBeNull();
  },
};

/* 5 */
export const ProjectAndHarness: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const popup = await openFilter(canvasElement, 'project');
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
    await expect(rowOf(canvasElement, 'B')?.querySelector('.next-operation-collision')).toBeNull();
    await pick(popup, 'compass');
    await pick(popup, 'recce/compass');
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(8));
    await closeFilters(canvasElement);
    await expect(chips(canvasElement)).toEqual(['Project: compass, recce/compass']);
    await expect(
      canvas.getByRole('button', { name: 'Remove Project: compass, recce/compass' }),
    ).toBeVisible();
    const again = await openFilter(canvasElement, 'project');
    await userEvent.click(within(again).getByRole('button', { name: 'Clear project filter' }));
    await waitFor(() => expect(chips(canvasElement)).toEqual([]));
    await expect(options(again, 'project')[0]?.box).toHaveFocus();
    await closeFilters(canvasElement);
    const harness = within(
      within(await openPanel(canvasElement)).getByRole('group', { name: 'Agent' }),
    );
    const labels = harness
      .getAllByRole('button')
      .map((button) => button.textContent?.trim().replace(/\s*\d+$/, ''));
    await expect(labels).toEqual([
      'Claude Code',
      'Codex',
      'Gemini',
      'Cursor',
      'Pi',
      'Goose',
      'OpenCode',
      'Droid',
    ]);
    await expect(harness.getByRole('button', { name: /Droid/ })).toBeDisabled();
    await expect(harness.getByText('Store could not be read')).toBeVisible();
  },
};

/* 6 */
export const AWaitingSessionIsNeverHiddenSilently: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    await pick(await openFilter(canvasElement, 'project'), 'recce-cloud-infra');
    await closeFilters(canvasElement);
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
    const primary = within(canvas.getByRole('navigation', { name: 'Primary' }));
    await expect(primary.getByRole('link', { name: /^Needs you [1-9]\d*$/ })).toBeVisible();
    const back = canvasElement.querySelector('[data-sessions-hidden-waiting]') as HTMLElement;
    await poll({ bWaiting: true });
    const needs = await within(back).findByRole('link', { name: 'See them on Needs you' });
    await expect(needs).toHaveAttribute('href', '#n=attention');
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
    await expect(within(nothing).getByText('Nothing here matches.')).toBeVisible();
    await expect(nothing.querySelectorAll('p')).toHaveLength(1);
    const older = canvas.getByRole('link', { name: 'Show older sessions' });
    await expect(older.parentElement).toHaveTextContent('Your filters are not kept.');
    await expect(nothing.compareDocumentPosition(older) & FOLLOWS).toBeTruthy();
    await expect(shownLines(canvasElement)).toEqual([]);
    await expect(
      canvasElement.querySelectorAll('[data-next-sessions-filtered-empty]'),
    ).toHaveLength(0);
    await expect(canvasElement.querySelectorAll('.next-sessions-empty')).toHaveLength(0);
    await expect(headerText(canvasElement, 'active')).toBe(ACTIVE_HEADER);
    await expect(headerText(canvasElement, 'history')).toBe(HISTORY_HEADER);
    await expect(
      [...canvasElement.querySelectorAll('[data-sessions-group-count]')].map(
        (count) => count.textContent,
      ),
    ).toEqual(['0 sessions', '0 sessions']);
    const reset = within(nothing).getByRole('button', { name: 'Show everything' });
    await expect(reset).toBeVisible();
    await expect(reset).toHaveStyle({
      backgroundColor: 'rgba(0, 0, 0, 0)',
      borderWidth: '0px',
      textDecorationLine: 'underline',
    });
  },
};

/* 8 */
export const StateAndDrift: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const state = await openFilter(canvasElement, 'state');
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
      'Codex, OpenCode and Pi report a wait only in some setups. See coverage on Needs you.',
    ]);
    await closeFilters(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Clear all' }));
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(12));
    const drift = await openFilter(canvasElement, 'drift');
    const listed = options(drift, 'drift');
    await expect(listed.map((one) => one.count)).toEqual([null, null, null]);
    for (const one of listed) await expect(one.label).not.toMatch(/no drift|on track/i);
    await pick(drift, 'Departure recorded');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('D'));
    await expect(rowOf(canvasElement, 'D')?.querySelector('[data-variant="progress"]')).toBeNull();
    await expect(options(drift, 'drift')[0]?.box).toHaveAttribute('aria-checked', 'true');
  },
};

/* 9 */
export const Goal: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const goal = await openFilter(canvasElement, 'goal');
    const counts = options(goal, 'goal').map((one) => Number(one.count));
    await expect(counts).toEqual([2, 0, 0]);
    await pick(goal, 'Goal saved');
    await waitFor(() => expect(shownRows(canvasElement)).toBe('BK'));
    const after = options(goal, 'goal').map((one) => Number(one.count));
    await expect(after).toEqual(counts);
  },
};

/* 10 */
export const FiltersSurviveAPollAndARoundTrip: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const box = canvas.getByRole('searchbox', { name: 'Search sessions' }) as HTMLInputElement;
    await userEvent.type(box, 'release');
    await pick(await openFilter(canvasElement, 'project'), 'recce/compass');
    await closeFilters(canvasElement);
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
    // Escape from a filter returns to the Filters button.
    const project = filtersButton(canvasElement);
    const projectOptions = await openFilter(canvasElement, 'project');
    within(projectOptions).getAllByRole('checkbox')[0]?.focus();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(project).toHaveAttribute('aria-expanded', 'false'));
    await expect(project).toHaveFocus();
    // The open panel gets the first Escape, and the field keeps its words.
    await userEvent.type(box, 'rel');
    const date = filtersButton(canvasElement);
    await openFilter(canvasElement, 'date');
    await dispatchKey(box, 'Escape');
    await waitFor(() => expect(date).toHaveAttribute('aria-expanded', 'false'));
    await expect(box.value).toBe('rel');
    // A pasted id prefix that finds one session opens it on Enter.
    await userEvent.clear(box);
    box.focus();
    await userEvent.paste(SIDS.C.slice(0, 8));
    await waitFor(() => expect(resultText(canvasElement)).toContain('Press Enter to open it.'));
    const matchingRow = rowOf(canvasElement, 'C');
    if (!matchingRow) throw new Error('Missing matching session');
    await expect(matchingRow.querySelector('[data-next-row-hint]')).toHaveTextContent(
      /^Matched in the session ID$/,
    );
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
      const state = await openFilter(canvasElement, 'state');
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
      await closeFilters(canvasElement);
      // A second press that lands on the same count says it again, so the reader hears their press counted.
      const same = writes;
      await pick(await openFilter(canvasElement, 'project'), 'projects/pendulum-of-despair');
      await waitFor(() => expect(writes).toBe(same + 1));
      await expect(region).toHaveTextContent('Showing 1 of 12 sessions.');
      await closeFilters(canvasElement);
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
  play: async ({ canvasElement }) => phoneWidth(canvasElement),
};

async function phoneWidth(canvasElement: HTMLElement) {
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
      const popup = await openFilter(canvasElement, 'state');
      for (const row of popup.querySelectorAll<HTMLElement>('[data-filter-option]'))
        await expect(row.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
      const panel = canvas.getByRole('region', { name: 'Filters' });
      await expect(panel.getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth);
      await closeFilters(canvasElement);
    });
  await userEvent.click(canvas.getByRole('button', { name: 'Waiting on you 1' }));
  await userEvent.click(await startedToday(canvasElement));
  await pick(await openFilter(canvasElement, 'project'), 'projects/pendulum-of-despair');
  await closeFilters(canvasElement);
  await waitFor(() => expect(chips(canvasElement)).toHaveLength(3));
  for (const width of [400, 360, 1280])
    await atWidth(width, async () => {
      await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
    });
}

/* 14 */
export const AllStoredSessions: Story = {
  args: { showAll: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('search', { name: 'Find sessions' });
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(15),
    );
    const popup = await openFilter(canvasElement, 'date');
    const note = canvasElement.querySelector('[data-sessions-all-note]') as HTMLElement;
    await expect(note).toHaveTextContent(
      'Showing all stored sessions. Sessions not active in the last 24 hours were not fully read, so their start time, title or model may not be published.',
    );
    await waitFor(() =>
      expect(within(note).getByRole('link', { name: 'Show only the last 24 hours' })).toBeVisible(),
    );
    await pick(popup, 'Last 7 days');
    await closeFilters(canvasElement);
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
    const drift = await openFilter(canvasElement, 'drift');
    await expect(drift).toHaveTextContent(
      'Progress records are not published because annotations are off.',
    );
    await closeFilters(canvasElement);
    const goal = await openFilter(canvasElement, 'goal');
    await expect(goal).toHaveTextContent('Goals are not published because annotations are off.');
    await closeFilters(canvasElement);
    await expect(canvas.queryByRole('button', { name: 'Departure recorded' })).toBeNull();
  },
};

/* 16 */
export const PaintHoldWhileAFilterIsOpen: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const { shell } = current();
    const counts = () =>
      options(
        canvasElement.querySelector<HTMLElement>('[data-filter-facet="state"]') as HTMLElement,
        'state',
      ).map((one) => `${one.label} ${one.count ?? ''}`);
    const panel = await openPanel(canvasElement);
    const projects = within(panel).getByRole('group', { name: 'Project' });
    const optionsBefore = projects.textContent;
    const agents = within(panel).getByRole('group', { name: 'Agent' });
    const agentsBefore = agents.textContent;
    await openFilter(canvasElement, 'state');
    const before = counts();
    await expect(before).toEqual([
      'Waiting on you 1',
      'Working 2',
      'Quiet 1',
      'Ended 1',
      'Waiting on child 0',
      'State not published 7',
    ]);
    await poll({ bIdle: true, bProject: 'aaa/new project' });
    await expect(shell.runtime.store.getSnapshot().acceptedCount).toBeGreaterThan(1);
    await expect(shell.display.hasPending()).toBe(true);
    await expect(counts()).toEqual(before);
    await expect(projects.textContent).toBe(optionsBefore);
    await expect(agents.textContent).toBe(agentsBefore);
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
      await closeFilters(canvasElement);
      await waitFor(() =>
        expect(counts()).toEqual([
          'Waiting on you 1',
          'Working 1',
          'Quiet 2',
          'Ended 1',
          'Waiting on child 0',
          'State not published 7',
        ]),
      );
      await expect(painted).toBe(1);
      await openPanel(canvasElement);
      await expect(projects).toHaveTextContent('aaa/new project');
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
    const state = await openFilter(canvasElement, 'state');
    await pick(state, 'Quiet');
    await waitFor(() => expect(shownRows(canvasElement)).not.toContain('C'));
    (document.activeElement as HTMLElement | null)?.blur();
    await expect(shell.controls.focusLane.focus('state:Quiet')).toBe(true);
    await expect(options(state, 'state').find((one) => one.label === 'Quiet')?.box).toHaveFocus();
    await closeFilters(canvasElement);
    await waitFor(() => expect(filtersButton(canvasElement)).toHaveFocus());
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

export const TabsAndInlineFilters: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const group = within(canvas.getByRole('group', { name: 'Session status' }));
    const tabs = group.getAllByRole('button');
    const words = [
      SESSION_LIST_WORDS.allTab,
      SESSION_ROW_WORDS.waitingOnYou,
      SESSION_ROW_WORDS.worthALook,
      SESSION_ROW_WORDS.working,
      SESSION_ROW_WORDS.quiet,
      SESSION_ROW_WORDS.ended,
    ];
    await expect(tabs.map((tab) => tab.textContent?.trim().replace(/\s*\d+$/, ''))).toEqual(words);
    for (const tab of tabs) {
      await expect(tab).toHaveAttribute('aria-pressed', tab === tabs[0] ? 'true' : 'false');
      await expect(tab.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    }
    await userEvent.click(group.getByRole('button', { name: /^Working \d/ }));
    await waitFor(() => expect(shownRows(canvasElement)).toHaveLength(2));
    const filters = canvas.getByRole('button', { name: 'Filters' });
    await expect(filters.querySelector('svg[data-icon="filters"]')).not.toBeNull();
    await userEvent.click(filters);
    const panel = canvas.getByRole('region', { name: 'Filters' });
    await expect(
      filters.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const progress = within(panel).getByRole('group', { name: 'Progress check' });
    await expect(
      within(progress)
        .getAllByRole('button')
        .map((chip) => chip.textContent),
    ).toEqual(['Slightly off course', 'Off course', 'Way off course', 'No goal yet']);
    for (const name of ['Slightly off course', 'Off course', 'Way off course']) {
      await expect(within(progress).getByRole('button', { name })).toBeDisabled();
    }
    await expect(
      within(progress).getByText(/Filtering by progress level is unavailable/),
    ).toBeVisible();
    await expect(shownRows(canvasElement)).toHaveLength(2);
    await userEvent.click(
      within(panel).getByRole('button', { name: 'More filters for power users' }),
    );
    for (const name of [
      'Project',
      'Agent',
      'Started',
      'Group',
      'Headless',
      'State',
      'Progress records',
      'Goal source',
    ]) {
      await waitFor(() => expect(within(panel).getAllByRole('group', { name })[0]).toBeVisible());
    }
    for (const name of ['Filter by', 'When']) {
      await expect(within(panel).getByRole('radiogroup', { name })).toBeVisible();
    }
    await expect(within(panel).getByRole('button', { name: 'Group by group' })).toBeVisible();
    await expect(panel.innerText).not.toMatch(/\b(?:Finished|Paused|Idle|Not checked)\s*($|\n)/m);
  },
};

export const MixedGoalEvidence: Story = {
  args: { goalEvidence: true },
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const panel = within(await openPanel(canvasElement));
    const progress = within(panel.getByRole('group', { name: 'Progress check' }));
    await expect(
      progress.getByText(/Goal filters skip sessions whose saved goal status was not published/),
    ).toBeVisible();
    const noSavedGoal = progress.getByRole('button', { name: 'No goal yet' });
    await userEvent.click(noSavedGoal);
    await waitFor(() => expect(shownRows(canvasElement)).toBe('F'));
    await userEvent.click(noSavedGoal);
    const goal = await openFilter(canvasElement, 'goal');
    const noGoal = goal.querySelector('[data-filter-option="goal:none"]');
    await expect(noGoal?.querySelector('[data-filter-count]')).toHaveTextContent('1');
    await waitFor(() =>
      expect(
        within(goal).getByText(
          'Goal filters skip sessions whose saved goal status was not published.',
        ),
      ).toBeVisible(),
    );
  },
};

/* The segmented control as the redesign canvas draws it (owner, 2026-11-24): the chosen segment is a white
   tab whose border clears 3:1 against the track, and the rest are plain words on the track, which clear the
   4.5:1 text bar instead of carrying a border of their own. */
export const SegmentBoundaries: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const chosen = canvas.getByRole('button', { name: /^All \d/ });
    await expect(chosen).toHaveAttribute('aria-pressed', 'true');
    const edge = paintedControlColors(chosen, getComputedStyle(chosen).borderTopColor, 'border');
    if (!edge) throw new Error('The chosen segment has no measurable boundary.');
    await expect(contrastOf(edge.foreground, edge.background)).toBeGreaterThanOrEqual(3);
    const tab = canvas.getByRole('button', { name: /^Quiet \d/ });
    await expect(tab).toHaveAttribute('aria-pressed', 'false');
    await expect(getComputedStyle(tab).borderTopColor).toBe('rgba(0, 0, 0, 0)');
    const words = paintedColors(tab);
    if (!words) throw new Error('The segment words have no measurable backdrop.');
    await expect(contrastOf(words.foreground, words.background)).toBeGreaterThanOrEqual(4.5);
  },
};

export const SelectedChipHasNonColourCue: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const panel = within(await openPanel(canvasElement));
    const agent = within(panel.getByRole('group', { name: 'Agent' }));
    const chip = agent.getByRole('button', { name: /^Claude Code \d/ });
    const before = Number(getComputedStyle(chip).fontWeight);
    await userEvent.click(chip);
    await expect(chip).toHaveAttribute('aria-pressed', 'true');
    await expect(Number(getComputedStyle(chip).fontWeight)).toBeGreaterThan(before);
  },
};

export const OptionCaveatsAreVisible: Story = {
  play: async ({ canvasElement }) => {
    await ready(canvasElement);
    const panel = within(await openPanel(canvasElement));
    const agents = within(panel.getByRole('group', { name: 'Agent' }));
    const projects = within(panel.getByRole('group', { name: 'Project' }));
    await expect(agents.getByText('Store could not be read')).toBeVisible();
    const note = projects.getByText(/Label shared by more than one location/);
    await expect(note).toBeVisible();
    await expect(projects.getByRole('button', { name: /^compass \d/ })).toHaveAccessibleDescription(
      note.textContent ?? '',
    );
  },
};

export const SessionsHeadingUsesTypeScale: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const heading = canvas.getByRole('heading', { name: 'All sessions' });
    // The section-title step the canvas draws it at (owner, 2026-11-24).
    await expect(heading).toHaveStyle({ fontSize: '24px', fontWeight: '700' });
  },
};

/* The search field and the Filters button stay matched on the 12 px control radius they share (owner,
   2026-11-24), and the button's label takes the 600 weight every button now has. */
export const SearchAndFiltersShareTheControlRadius: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const search = getComputedStyle(canvas.getByRole('searchbox', { name: 'Search sessions' }));
    const filters = getComputedStyle(filtersButton(canvasElement));
    await expect(search.borderTopLeftRadius).toBe('12px');
    await expect(filters.borderTopLeftRadius).toBe(search.borderTopLeftRadius);
    await expect(filters.fontWeight).toBe('600');
  },
};

export const UnavailableSegmentsLookDisabled: Story = {
  args: { flagBoard: 'failed' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tab = await canvas.findByRole('button', { name: 'Working unavailable' });
    await expect(tab).toBeDisabled();
    const style = getComputedStyle(tab);
    await expect(style.cursor).toBe('not-allowed');
    // Calm, not hatched (owner, 2026-11-24): a solid outline over the muted fill.
    await expect(style.borderTopStyle).toBe('solid');
    await expect(style.backgroundImage).toBe('none');
    await expect(style.backgroundColor).toBe('rgb(238, 241, 244)');
    await expect(style.color).not.toBe(
      getComputedStyle(canvas.getByRole('button', { name: 'All unavailable' })).color,
    );
  },
};

export const CodexFiltersExplainUnavailableLevels: Story = {
  args: { flagBoard: 'codex' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('button', { name: 'All 1' });
    const panel = within(await openPanel(canvasElement));
    const progress = within(panel.getByRole('group', { name: 'Progress check' }));
    const explanation = 'Filtering by progress level is unavailable.';
    await expect(progress.getByText(explanation)).toBeVisible();
    for (const name of ['Slightly off course', 'Off course', 'Way off course']) {
      await expect(progress.getByRole('button', { name })).toBeDisabled();
    }
  },
};

export const AppliedProgressRecordUsesGlossaryWords: Story = {
  play: async ({ canvasElement }) => {
    const canvas = await ready(canvasElement);
    const progress = await openFilter(canvasElement, 'drift');
    const recorded = options(progress, 'drift')[0];
    if (!recorded?.box) throw new Error('Missing recorded progress option.');
    await userEvent.click(recorded.box);
    await waitFor(() => expect(shownRows(canvasElement)).toBe('D'));
    await closeFilters(canvasElement);
    await expect(
      canvas.getByRole('button', { name: 'Remove Progress records: Departure recorded' }),
    ).toBeVisible();
    await expect(canvas.queryByRole('region', { name: 'Filters' })).toBeNull();
  },
};
