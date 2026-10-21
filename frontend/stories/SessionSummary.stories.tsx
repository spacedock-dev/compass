import type { Meta, StoryObj } from '@storybook/react-vite';
import { openPhases, seeInContext } from './citation';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { SAMPLE_FIXTURE, SampleFixtureContext } from '../src/sample/fixture';
import { SAMPLE_FRAGMENT } from '../src/sample/ids';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment, type FakeClock } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import {
  FRESHNESS_UNKNOWN,
  GAP_RUNNING,
  PLACE_LINES,
  REPLY_CUT,
  SUMMARY_FAILED_SEND,
  SUMMARY_HOLDS,
  SUMMARY_INCOMPLETE,
  SUMMARY_LABEL,
  SUMMARY_OFF,
  SUMMARY_WORKING_KEEP,
  WITHHELD_LINES,
  withheldTitle,
} from '../src/sessions/summary';
import { OUTSIDE_WINDOW } from '../src/sessions/WhatItDid';
import { neverDone, noCheckMark } from './drift.checks';
import { COVERAGE, G, claudeOutline } from './outline.scenario';
import {
  ABSENT,
  FIRST_PHASE,
  LEDE,
  NOTICE,
  SECOND_PHASE,
  SummaryPage,
  block,
  bullet,
  defaultAnswer,
  departureReading,
  gap,
  grant,
  job,
  poll,
  script,
  storedSummary,
} from './summary.scenario';

/* The What the session has done card with a model-written summary, one story per state it can draw. Each mounts
   the real page over a scripted backend whose focused context carries `sources.summary` and whose board carries
   the `summaries` grant block, and asserts what a reader sees, which controls are there, and what was posted. */

const meta = { title: 'Sessions/What the session has done: summary' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const card = (root: HTMLElement) =>
  within(root).findByRole('region', { name: 'What the session has done' });
const summaryOf = (region: HTMLElement) =>
  waitFor(() => {
    const node = region.querySelector<HTMLElement>('[data-next-summary]');
    if (!node) throw new Error('no summary yet');
    return node;
  });
const stateOf = (region: HTMLElement, state: string) =>
  waitFor(() => {
    const node = region.querySelector<HTMLElement>(`[data-next-summary-state="${state}"]`);
    if (!node) throw new Error(`no ${state} state yet`);
    return node;
  });
const summaryPosts = () => script.posts.filter((post) => post.path === '/api/summary');
const frames = () =>
  new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const entryRow = (root: HTMLElement, id: string) =>
  root.querySelector(`[data-next-cockpit-work] [data-next-entry-id="${id}"]`);

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

/* Each `said` bullet names the agent as its speaker and cites only the agent's messages; each `asked` opens with "You" and
   cites only the person's; a `failed` one says so in words; every chip is named for the bullet it supports and
   names a row of Full activity. */
async function attributed(summary: HTMLElement) {
  const bullets = [...summary.querySelectorAll<HTMLElement>('[data-next-summary-bullet]')];
  await expect(bullets.length).toBeGreaterThan(0);
  for (const row of bullets) {
    const kind = row.dataset['nextSummaryBullet'];
    const words = row.querySelector('[data-next-summary-text]')?.textContent ?? '';
    const chips = [...row.querySelectorAll<HTMLElement>('[data-next-outline-entry]')];
    await expect(chips.length).toBeGreaterThan(0);
    if (kind === 'said') await expect(words).toMatch(/^The agent (also )?said\b/);
    if (kind === 'asked') await expect(words).toMatch(/^You (asked|said)\b/);
    if (kind === 'failed') await expect(words).toMatch(/^Failed(?: as the tool reported)?: /);
    for (const chip of chips) {
      await expect(chip.getAttribute('aria-label')).toContain(`cited for “${words}”`);
      const id = chip.dataset['nextOutlineEntry'] ?? '';
      const entry = document.querySelector<HTMLElement>(
        `[data-next-cockpit-work] [data-next-entry-id="${CSS.escape(id)}"]`,
      );
      // Whose words a bullet cites is read off the entry Full activity draws for it.
      await expect(entry).not.toBeNull();
      if (kind === 'said') await expect(entry?.textContent).toMatch(/Agentsaid/);
      if (kind === 'asked') await expect(entry?.textContent).toMatch(/You/);
      if (entry) await expect(chip.textContent).toMatch(/^\[\d+(\.\d+)?\]$/);
    }
  }
}

/* Ready: the lede, then the phases as headings with their bullets, the model and the time in the header, and the
   card says nothing is done. */
export const Ready: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(summary.querySelector('[data-next-summary-label]')).toHaveTextContent(
      SUMMARY_LABEL,
    );
    // The stored paragraph says "The person"; the card draws it as "You", at the start of a sentence only.
    await expect(summary.querySelector('[data-next-summary-lede]')).toHaveTextContent(
      LEDE.replace(/^The person/, 'You'),
    );
    const headings = within(summary).getAllByRole('heading', { level: 3 });
    await expect(headings.map((node) => node.textContent)).toEqual([
      FIRST_PHASE.title,
      SECOND_PHASE.title,
    ]);
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^claude-sonnet-5-5 · summarized at \d\d:\d\d$/,
    );
    await waitFor(() =>
      expect(summary.querySelector('[data-next-outline-entry="a1"]')).toHaveTextContent('[2]'),
    );
    await attributed(summary);
    // The model wrote "Reverting the test edit." for a `said` bullet: it is drawn as the agent's words.
    await expect(summary).toHaveTextContent('The agent said: Reverting the test edit.');
    // A failed bullet takes the failure colour.
    const failed = summary.querySelector('[data-next-summary-bullet="failed"]') as HTMLElement;
    await expect(getComputedStyle(failed).color).toBe('rgb(228, 136, 106)');
    // The outline stays one press away, below the summary.
    await expect(
      within(region).getByRole('button', { name: "Compass's outline of this session" }),
    ).toBeVisible();
    await expect(within(region).getByRole('button', { name: 'Delete summary' })).toBeVisible();
    await neverDone(region);
    await noCheckMark(region);
    // Plain text: no element a model's words could have made.
    await expect(
      summary.querySelectorAll('a:not([data-next-outline-entry]), strong, em, code, img'),
    ).toHaveLength(0);
    // A chip opens Full activity at its entry.
    await seeInContext(within(summary).getByRole('link', { name: /^Open entry #2\.1, cited for/ }));
    await waitFor(() => expect(document.activeElement).toBe(entryRow(canvasElement, 'c1')));
    await expect(summaryPosts()).toHaveLength(0);
    for (const width of [1280, 400])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
  },
};

/* A model-written line that already names its subject takes no kind prefix, and the person is "you". These four
   are the lines a freshly written summary drew as "The agent said: The agent read ...", "The agent said: The agent
   opened ...", "You said: The person redirected ..." and "You said: The person chose ...". */
export const NamedSubjectsAreNotDoubled: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'a2', 4, [
            {
              title: 'Reading the gate',
              bullets: [
                bullet(
                  'The agent read the gate and its tests, then installed the pinned dependencies.',
                  'said',
                  ['a1'],
                ),
                bullet('The agent opened draft PR #638 and said the gate was waiting.', 'said', [
                  'a2',
                ]),
                bullet(
                  'The person redirected the agent to the goal: gate and tests only.',
                  'asked',
                  ['p1'],
                ),
                bullet('The person chose 54 named exceptions for the duplicates.', 'asked', ['p2']),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const lines = [
      ...summary.querySelectorAll<HTMLElement>(
        '[data-next-summary-bullet] [data-next-summary-text]',
      ),
    ].map((node) => node.textContent ?? '');
    await expect(lines).toEqual([
      'The agent read the gate and its tests, then installed the pinned dependencies.',
      'The agent opened draft PR #638 and said the gate was waiting.',
      'You redirected the agent to the goal: gate and tests only.',
      'You chose 54 named exceptions for the duplicates.',
    ]);
    for (const line of lines) {
      await expect(line).not.toContain('said: The agent');
      await expect(line).not.toContain('said: The person');
      await expect(line).not.toContain('You said: The person');
    }
    const asked = [
      ...summary.querySelectorAll('[data-next-summary-bullet="asked"] [data-next-summary-text]'),
    ];
    for (const node of asked) await expect(node.textContent).toMatch(/^You /);
  },
};

/* With Full activity closed, a chip opens it and the cited row lands on screen. A smooth scroll begun while
   the panel still grew was clamped at the foot of a page not yet tall enough and left the row at the edge. */
export const ChipLandsOnScreenWithFullActivityClosed: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(
      canvasElement
        .querySelector('[data-next-full-activity-trigger]')
        ?.getAttribute('aria-expanded'),
    ).toBe('false');
    await seeInContext(within(summary).getByRole('link', { name: /^Open entry #2\.1, cited for/ }));
    const row = await waitFor(() => {
      const node = entryRow(canvasElement, 'c1');
      expect(document.activeElement).toBe(node);
      return node as HTMLElement;
    });
    await waitFor(
      () => {
        // The row's head is on screen and clear of the foot, where the clamped scroll left it (728 of 729).
        const box = row.getBoundingClientRect();
        expect(box.top).toBeGreaterThanOrEqual(0);
        expect(box.top).toBeLessThanOrEqual(window.innerHeight - 80);
      },
      { timeout: 3000 },
    );
  },
};

/* Hovering a citation shows the cited entry's own words in a card, and nothing moves. The card's last line is
   the only way to Full activity: it closes the card and lands on the row. */
export const CitationCardShowsTheEntry: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const citation = within(summary).getByRole('link', { name: /^Open entry #2\.1, cited for/ });
    await expect(document.querySelector('[data-next-citation-card]')).toBeNull();
    await userEvent.hover(citation);
    const shown = await waitFor(() => {
      const node = document.querySelector<HTMLElement>('[data-next-citation-card]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(shown.querySelector('[data-next-citation-snippet]')?.textContent ?? '').not.toBe(
      '',
    );
    await expect(shown).toHaveTextContent('#2.1');
    // Seeing the entry did not open Full activity or move focus to it.
    await expect(
      canvasElement
        .querySelector('[data-next-full-activity-trigger]')
        ?.getAttribute('aria-expanded'),
    ).toBe('false');
    await userEvent.click(within(shown).getByText('See in context of the session'));
    await waitFor(() => expect(document.querySelector('[data-next-citation-card]')).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(entryRow(canvasElement, 'c1')));
  },
};

/* A running session's summary: the header says when it was updated and that the session still runs, and
   opening it posts nothing. */
export const ReadyStillRunning: Story = {
  render: () => <SummaryPage summary={storedSummary()} ended={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^claude-sonnet-5-5 · updated \d\d:\d\d · still running$/,
    );
    await poll();
    await expect(summaryPosts()).toHaveLength(0);
  },
};

/* An idle session that has not ended, such as a Codex session after its task completed: the stamp names when
   it was summarized and never says "still running", which the walk found on idle and completed sessions. */
export const ReadyIdleIsNotStillRunning: Story = {
  render: () => <SummaryPage summary={storedSummary()} ended={false} session={{ state: 'idle' }} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^claude-sonnet-5-5 · summarized at \d\d:\d\d$/,
    );
    await expect(region).not.toHaveTextContent('still running');
  },
};

/* No summary on a running session: the outline stays, with one sentence on what a summary adds, how large the
   read is, Summarize, and what is sent behind its own popover. Nothing is posted until the press. */
export const NoSummary: Story = {
  render: () => <SummaryPage summary={ABSENT} ended={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const none = await stateOf(region, 'none');
    // The way to ask for one stays above the outline, where it also stands once a summary opens or runs.
    await expect(none).not.toHaveTextContent(/tells this session as a short story/);
    const outline = region.querySelector('[data-next-outline="blocks"]');
    await expect(outline).not.toBeNull();
    await expect(
      none.compareDocumentPosition(outline as Element) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // The estimate sits beside Summarize, in the one row.
    const size = none.querySelector('[data-next-summary-size]') as HTMLElement;
    await expect(size).toHaveTextContent('About 8 entries to read.');
    const press = within(none).getByRole('button', { name: 'Summarize' });
    await expect(size.parentElement).toBe(press.parentElement);
    const sent = within(none).getByRole('button', { name: 'What is sent to Claude Code' });
    await userEvent.click(sent);
    await waitFor(() =>
      expect(
        within(document.body).getByRole('button', { name: 'Turn off summaries' }),
      ).toBeVisible(),
    );
    await userEvent.keyboard('{Escape}');
    await poll();
    await expect(summaryPosts()).toHaveLength(0);
    await userEvent.click(within(none).getByRole('button', { name: 'Summarize' }));
    await waitFor(() =>
      expect(summaryPosts()).toEqual([
        {
          path: '/api/summary',
          body: { harness: 'claude', sid: 's1', action: 'start', origin: 'press' },
        },
      ]),
    );
  },
};

const PLAN = {
  reason: null,
  complete: true,
  parts: 4,
  windows: 3,
  calls: 8,
  minutes: 10,
  largest_read: {
    windows: 32,
    window_bytes: 16384,
    calls: 37,
    bytes_sent: 786432,
    seconds: 600,
    call_timeout: 180,
  },
};

/* With the server's plan the card says the parts and an upper bound on the minutes before anything runs. */
export const NoSummaryPlanned: Story = {
  render: () => <SummaryPage summary={{ ...ABSENT, plan: PLAN }} ended={false} />,
  play: async ({ canvasElement }) => {
    const none = await stateOf(await card(canvasElement), 'none');
    await expect(none.querySelector('[data-next-summary-size]')).toHaveTextContent(
      /^About 8 entries to read in 4 parts, up to 10 minutes\.$/,
    );
    await poll();
    await expect(summaryPosts()).toHaveLength(0);
  },
};

/* A plan off a partial outline read, one that starts past the transcript's first byte, is a floor on the entries
   and on the parts; one the preflight would refuse is not quoted. */
export const NoSummaryPlannedPartly: Story = {
  render: () => (
    <SummaryPage
      summary={{ ...ABSENT, plan: { ...PLAN, complete: false, parts: 1, windows: 0, minutes: 1 } }}
      outline={claudeOutline(
        { coverage: { ...COVERAGE, complete: false, start_offset: 2048 } },
        true,
      )}
      ended={false}
    />
  ),
  play: async ({ canvasElement }) => {
    const none = await stateOf(await card(canvasElement), 'none');
    // A floor on the parts is not quoted: the job's own count may pass it, and the progress line would disagree.
    await expect(none.querySelector('[data-next-summary-size]')).toHaveTextContent(
      /^More than 8 entries to read\. Compass plans the parts when the summary starts, and shows them here\.$/,
    );
  },
};

/* A finished session with no summary posts one open start, once per page load, and shows its progress and the
   first-summary notice with the off switch beside it. Later polls post nothing more. */
export const AutoStartsOnceOnOpen: Story = {
  render: () => (
    <SummaryPage
      summary={ABSENT}
      answer={(path, body) => {
        if (path === '/api/summary' && body['origin'] === 'open') {
          script.summary = { ...ABSENT, job: job({ part: 1, notice: NOTICE }) };
          return { status: 202, body: { ok: true, job: job({ notice: NOTICE }), notice: NOTICE } };
        }
        return defaultAnswer(path, body);
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await waitFor(() =>
      expect(summaryPosts()).toEqual([
        {
          path: '/api/summary',
          body: { harness: 'claude', sid: 's1', action: 'start', origin: 'open' },
        },
      ]),
    );
    const working = await stateOf(region, 'working');
    await expect(working.querySelector('[data-next-summary-progress]')).toHaveTextContent(
      'Summarizing: part 1 of 3',
    );
    await expect(working).toHaveTextContent(SUMMARY_WORKING_KEEP);
    const notice = working.querySelector('[data-next-summary-notice]') as HTMLElement;
    await expect(notice).not.toBeNull();
    await expect(notice).toHaveTextContent('Claude Code');
    await expect(notice).toHaveTextContent('Anthropic');
    await expect(within(notice).getByRole('button', { name: 'Turn off summaries' })).toBeVisible();
    await poll();
    await poll();
    await expect(summaryPosts()).toHaveLength(1);
  },
};

/* Summaries turned off: the outline with Turn summaries on, and no summary call on open or on a poll. */
export const OffStaysOff: Story = {
  render: () => (
    <SummaryPage
      summary={ABSENT}
      grant={grant({ consent: false, off: true, reason: 'summaries-off' })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const off = await stateOf(region, 'off');
    await expect(off).toHaveTextContent(SUMMARY_OFF);
    await expect(within(off).getByRole('button', { name: 'Turn summaries on' })).toBeVisible();
    await expect(region.querySelector('[data-next-outline="blocks"]')).not.toBeNull();
    await poll();
    await poll();
    await expect(script.posts).toHaveLength(0);
    await userEvent.click(within(off).getByRole('button', { name: 'Turn summaries on' }));
    await waitFor(() =>
      expect(script.posts[0]).toEqual({ path: '/api/summary', body: { consent: 'on' } }),
    );
    // Turning summaries on is not an open: the finished session is not summarized on this page load.
    await stateOf(region, 'none');
    await poll();
    await poll();
    await expect(script.posts).toEqual([{ path: '/api/summary', body: { consent: 'on' } }]);
  },
};

/* Working: the parts done so far, Cancel, and the reader told they can keep working. Cancel posts once. */
export const Working: Story = {
  render: () => (
    <SummaryPage
      summary={{ ...ABSENT, job: job({ part: 3, parts: 12, finished_parts: [1, 2] }) }}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const working = await stateOf(region, 'working');
    await expect(working.querySelector('[data-next-summary-progress]')).toHaveTextContent(
      'Summarizing: part 3 of 12',
    );
    await expect(working).toHaveTextContent(SUMMARY_WORKING_KEEP);
    // Turn off summaries turns off every session's summaries, where Cancel stops this run: it stands apart from
    // Cancel, in a row of its own and as a quiet control, and not as an equal button beside it.
    const cancel = within(working).getByRole('button', { name: 'Cancel' });
    const off = within(working).getByRole('button', { name: 'Turn off summaries' });
    await expect(off.parentElement).not.toBe(cancel.parentElement);
    await expect(cancel).toHaveAttribute('data-variant', 'default');
    await expect(off).toHaveAttribute('data-variant', 'quiet');
    await expect(region.querySelector('[data-next-outline="blocks"]')).not.toBeNull();
    await userEvent.click(within(working).getByRole('button', { name: 'Cancel' }));
    await waitFor(() =>
      expect(script.posts).toEqual([
        { path: '/api/summary/cancel', body: { harness: 'claude', sid: 's1' } },
      ]),
    );
    await expect(summaryPosts()).toHaveLength(0);
  },
};

/* A summary still being built by an Update: the saved part stands, and the part not yet read says so. */
export const WorkingOverASavedSummary: Story = {
  render: () => (
    <SummaryPage
      ended={false}
      summary={storedSummary({
        blocks: [block('p1', 'c2', 4, [FIRST_PHASE]), gap('p2', 'a2', 2, 'stopped')],
        job: job({ part: 2, parts: 3, finished_parts: [1] }),
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await stateOf(region, 'working');
    const summary = await summaryOf(region);
    await expect(summary.querySelector('[data-next-summary-gap="stopped"]')).toHaveTextContent(
      GAP_RUNNING,
    );
    // The header does not date a summary a job is still writing.
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^claude-sonnet-5-5 · summarizing…$/,
    );
  },
};

/* Out of date by an append: how many entries arrived since the summary, and Update summary posts an update. */
export const OutOfDateNewEntries: Story = {
  render: () => (
    <SummaryPage
      ended={false}
      summary={storedSummary({
        out_of_date: {
          kind: 'appended',
          reason: null,
          affected_blocks: [],
          new_entries: 12,
          appendable: true,
          action: 'update',
        },
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const line = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-summary-outdated]');
      if (!node) throw new Error('no out-of-date line');
      return node;
    });
    await expect(line).toHaveTextContent(/^12 new entries since \d\d:\d\d\.Update summary$/);
    await userEvent.click(within(line).getByRole('button', { name: 'Update summary' }));
    await waitFor(() =>
      expect(summaryPosts()).toEqual([
        {
          path: '/api/summary',
          body: { harness: 'claude', sid: 's1', action: 'update', origin: 'press' },
        },
      ]),
    );
  },
};

/* Out of date by an earlier change: the reason names the block it affects, and Summarize again posts a rerun. */
export const OutOfDateChangedEarlier: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        out_of_date: {
          kind: 'changed_earlier',
          reason: 'changed_earlier',
          affected_blocks: [0],
          new_entries: 0,
          appendable: false,
          action: 'summarize_again',
        },
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const line = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-summary-outdated]');
      if (!node) throw new Error('no out-of-date line');
      return node;
    });
    await expect(line).toHaveTextContent(
      `An earlier entry of the session changed after this summary was made. It affects the part “${FIRST_PHASE.title}”.`,
    );
    await userEvent.click(within(line).getByRole('button', { name: 'Summarize again' }));
    await waitFor(() =>
      expect(summaryPosts()[0]?.body).toEqual({
        harness: 'claude',
        sid: 's1',
        action: 'rerun',
        origin: 'press',
      }),
    );
  },
};

/* Freshness that could not be told says so, and offers nothing it cannot back. */
export const FreshnessUnknown: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        out_of_date: {
          kind: 'unavailable',
          reason: 'source_incomplete',
          affected_blocks: [],
          new_entries: 0,
          appendable: false,
          action: null,
        },
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await waitFor(() => expect(region).toHaveTextContent(FRESHNESS_UNKNOWN));
    await expect(within(region).queryByRole('button', { name: 'Update summary' })).toBeNull();
  },
};

/* Partial: a withheld bullet and a gap say so in place, and a summary that starts partway says where. */
export const Partial: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        state: 'partial',
        reason: 'gaps',
        starts_at: 'p2',
        blocks: [
          gap('p1', 'c2', 4, 'before_window'),
          block('p2', 'a2', 2, [
            {
              ...SECOND_PHASE,
              bullets: [
                ...SECOND_PHASE.bullets,
                bullet({ withheld: true, reason: 'completion_claim' }, 'did', ['a2']),
              ],
            },
            {
              title: { withheld: true, reason: 'completion_claim' },
              bullets: [bullet('Asked for the tests to stay as they were.', 'asked', ['p2'])],
            },
          ]),
          gap('a2', 'a2', 1, 'no_output'),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await waitFor(() =>
      expect(summary.querySelector('[data-next-summary-note]')).toHaveTextContent(
        'This summary starts at #3, not at the session’s first entry.',
      ),
    );
    await expect(summary.querySelector('[data-next-summary-gap="before_window"]')).toBeTruthy();
    await expect(summary.querySelector('[data-next-summary-gap="no_output"]')).toHaveTextContent(
      'This part could not be summarized: the model returned nothing, twice. (1 entry)',
    );
    const withheld = summary.querySelector('li [data-next-summary-withheld="completion_claim"]');
    await expect(withheld).toHaveTextContent(WITHHELD_LINES.completion_claim ?? '');
    await expect(
      summary.querySelector('h3 [data-next-summary-withheld="completion_claim"]'),
    ).toHaveTextContent(withheldTitle('completion_claim'));
    await neverDone(region);
  },
};

/* Interrupted with no saved summary: the reason in the reader's words, the parts it kept, Summarize, and the
   outline above it. */
export const Interrupted: Story = {
  render: () => (
    <SummaryPage
      summary={{
        ...ABSENT,
        job: job({ state: 'interrupted', reason: 'interrupted', parts: 5, finished_parts: [] }),
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const none = await stateOf(region, 'none');
    await expect(none.querySelector('[data-next-summary-reason]')).toHaveTextContent(
      'Compass restarted while this summary ran, so it stopped. It does not resume on its own. It kept no part.',
    );
    await expect(within(none).getByRole('button', { name: 'Summarize' })).toBeVisible();
    await expect(region.querySelector('[data-next-outline="blocks"]')).not.toBeNull();
    await poll();
    await expect(summaryPosts()).toHaveLength(0);
  },
};

/* Cancelled after two parts: the saved summary stands, with what the cancel kept said beside it. */
export const CancelledKeepsParts: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        state: 'partial',
        blocks: [block('p1', 'c2', 4, [FIRST_PHASE]), gap('p2', 'a2', 2, 'stopped')],
        job: job({ state: 'cancelled', reason: 'cancelled', parts: 3, finished_parts: [1, 2] }),
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(region.querySelector('[data-next-summary-reason]')).toHaveTextContent(
      'You cancelled the summary. It kept 2 parts of 3.',
    );
    await expect(summary.querySelector('[data-next-summary-gap="stopped"]')).toHaveTextContent(
      'This part was not summarized: the summary stopped before it.',
    );
  },
};

/* At its cap: the reason with when it can run again, no Summarize, no post on open. */
export const AtItsCap: Story = {
  render: () => (
    <SummaryPage
      summary={ABSENT}
      grant={grant({ reason: 'daily-cap', used: 200, retry_at: 1900003600 })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const blocked = await stateOf(region, 'blocked');
    await expect(blocked.querySelector('[data-next-summary-reason="daily-cap"]')).toHaveTextContent(
      /^Summaries have used their 200 model calls for the last 24 hours\. They can run again at \d\d:\d\d\.$/,
    );
    await expect(within(blocked).queryByRole('button', { name: 'Summarize' })).toBeNull();
    await expect(within(blocked).getByRole('button', { name: 'Turn off summaries' })).toBeVisible();
    await poll();
    await expect(script.posts).toHaveLength(0);
  },
};

/* A press the server refuses before any call: the largest read allowed, and nothing sent. */
export const RefusedTooLarge: Story = {
  render: () => (
    <SummaryPage
      summary={ABSENT}
      ended={false}
      answer={() => ({
        status: 422,
        body: {
          ok: false,
          reason: 'planned_calls',
          parts: 40,
          largest_read: {
            windows: 32,
            window_bytes: 16384,
            calls: 37,
            bytes_sent: 786432,
            seconds: 600,
            call_timeout: 180,
          },
        },
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const none = await stateOf(region, 'none');
    await userEvent.click(within(none).getByRole('button', { name: 'Summarize' }));
    await waitFor(() =>
      expect(region.querySelector('[data-next-summary-reason="planned_calls"]')).toHaveTextContent(
        'This session is larger than one summary may read: at most 32 parts of 16 KiB, 37 model calls and 10 minutes. Nothing was sent.',
      ),
    );
  },
};

/* The master pause leaves the summary switch visible and disabled. */
export const ModelCallsPaused: Story = {
  render: () => (
    <SummaryPage summary={ABSENT} grant={grant({ consent: false, reason: 'model-calls-paused' })} />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const blocked = await stateOf(region, 'blocked');
    await expect(blocked).toHaveTextContent(
      'Model calls are paused. Nothing is sent for a session summary until you resume.',
    );
    const toggle = within(blocked).getByRole('button', { name: 'Turn off summaries' });
    await expect(toggle).toHaveAttribute('aria-disabled', 'true');
    await expect(within(blocked).getByText('Model calls are paused')).toBeVisible();
    await userEvent.click(toggle);
    await poll();
    await expect(script.posts).toHaveLength(0);
    const resume = within(canvasElement).getByRole('button', { name: 'Resume model calls' });
    await userEvent.click(resume);
    await waitFor(() => expect(script.masterPosts).toHaveLength(1));
    await waitFor(() => expect(script.paused).toBe(false));
    await userEvent.click(await within(region).findByRole('button', { name: /What is sent/ }));
    const restored = await within(document.body).findByRole('button', {
      name: 'Turn off summaries',
    });
    await expect(restored).not.toHaveAttribute('aria-disabled', 'true');
    await expect(script.grant?.['off']).toBe(false);
    await expect(script.posts).toHaveLength(0);
  },
};

export const ResumeKeepsSummariesOff: Story = {
  render: () => (
    <SummaryPage
      ended={false}
      grant={grant({ consent: false, off: true, reason: 'model-calls-paused' })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const toggle = within(region).getByRole('button', { name: 'Turn summaries on' });
    await expect(toggle).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(toggle);
    await expect(script.posts).toHaveLength(0);
    await userEvent.click(
      within(canvasElement).getByRole('button', { name: 'Resume model calls' }),
    );
    await waitFor(() => expect(toggle).not.toHaveAttribute('aria-disabled', 'true'));
    await expect(within(region).getByText(SUMMARY_OFF)).toBeVisible();
    await expect(script.grant?.['off']).toBe(true);
    await expect(script.posts).toHaveLength(0);
  },
};

export const PauseStopsARunningSummary: Story = {
  render: () => <SummaryPage summary={storedSummary({ job: job({ part: 1 }) })} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await stateOf(region, 'working');
    const drift = within(canvasElement).getByRole('region', { name: 'Drift' });
    await userEvent.click(within(drift).getByRole('button', { name: /What is sent/ }));
    // The copy inside What is sent; the Drift card head holds another.
    await userEvent.click(
      await waitFor(() => {
        const found = within(document.body)
          .getAllByRole('button', { name: 'Pause model calls' })
          .find((node) => node.closest('[data-slot="popover-content"]'));
        expect(found).toBeDefined();
        return found as HTMLElement;
      }),
    );
    await waitFor(() =>
      expect(script.summary?.['job']).toMatchObject({
        state: 'stopping',
        reason: 'model-calls-paused',
      }),
    );
    await expect(
      within(region).getByRole('button', { name: 'Turn off summaries' }),
    ).toHaveAttribute('aria-disabled', 'true');
    await expect(within(region).getByText('Model calls are paused')).toBeVisible();
    await expect(script.posts).toHaveLength(0);
  },
};

/* A server that publishes no summaries draws the outline alone, as before. */
export const NoSummariesOnThisServer: Story = {
  render: () => <SummaryPage summary={null} grant={null} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await waitFor(() =>
      expect(region.querySelector('[data-next-outline="blocks"]')).not.toBeNull(),
    );
    const controls = region.querySelector('[data-next-session-summary-controls]') as HTMLElement;
    await expect(controls).toBeEmptyDOMElement();
    await poll();
    await expect(script.posts).toHaveLength(0);
  },
};

/* The notice: shown with the first summary, gone when a later start's reply carries none, and shown again
   naming the new destination when where summaries go changes. Once the summary stands the notice is folded to
   one line, and opening it shows what it said, with Turn off summaries inside. */
export const NoticeOnceThenAgainOnChange: Story = {
  render: () => {
    let n = 0;
    return (
      <SummaryPage
        ended={false}
        summary={storedSummary({
          out_of_date: {
            kind: 'appended',
            reason: null,
            affected_blocks: [],
            new_entries: 2,
            appendable: true,
            action: 'update',
          },
        })}
        answer={(path, body) => {
          if (path !== '/api/summary' || 'consent' in body) return defaultAnswer(path, body);
          n += 1;
          const notice =
            n === 1 ? NOTICE : n === 3 ? { ...NOTICE, destination: 'gateway.example' } : null;
          return {
            status: 202,
            body: {
              ok: true,
              job: job({ state: 'complete', notice }),
              ...(notice ? { notice } : {}),
            },
          };
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const press = async () => {
      const before = summaryPosts().length;
      const button = await within(region).findByRole('button', { name: 'Update summary' });
      await userEvent.click(button);
      await waitFor(() => expect(summaryPosts()).toHaveLength(before + 1));
      await waitFor(() => expect(button).not.toHaveAttribute('aria-busy'));
    };
    await press();
    const first = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-summary-notice]');
      if (!node) throw new Error('no notice');
      return node;
    });
    await expect(first).toHaveAttribute('data-next-summary-notice-folded');
    const fold = within(first).getByRole('button', {
      name: 'What this request sent to Claude Code',
    });
    await expect(fold).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(fold);
    await expect(first).toHaveTextContent('Anthropic');
    await waitFor(() =>
      expect(within(first).getByRole('button', { name: 'Turn off summaries' })).toBeVisible(),
    );
    await press();
    await waitFor(() => expect(region.querySelector('[data-next-summary-notice]')).toBeNull());
    await press();
    await waitFor(() =>
      expect(region.querySelector('[data-next-summary-notice]')).toHaveTextContent(
        'gateway.example',
      ),
    );
    await expect(summaryPosts()).toHaveLength(3);
  },
};

/* The second part with the check the reading's departure cites, after the reader's words were saved. */
const CHECK_PHASE = {
  ...SECOND_PHASE,
  bullets: [
    ...SECOND_PHASE.bullets,
    bullet('pytest tests/test_webhook.py reported failed, as the tool reported.', 'failed', ['c3']),
  ],
};
const withCheck = (over: Record<string, unknown> = {}) =>
  storedSummary({
    blocks: [block('p1', 'c2', 4, [FIRST_PHASE]), block('p2', 'a3', 4, [CHECK_PHASE])],
    ...over,
  });

/* Departure evidence in a phase: the phase is marked and links to the departure card, which links back. */
export const DepartureMarked: Story = {
  render: () => <SummaryPage summary={withCheck()} session={departureReading(['c3'])} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const marked = await waitFor(() => {
      const node = summary.querySelector<HTMLElement>('[data-next-summary-marked]');
      if (!node) throw new Error('no marked phase');
      return node;
    });
    await expect(marked.dataset['nextSummaryPhase']).toBe('1:0');
    await expect(summary.querySelectorAll('[data-next-summary-marked]')).toHaveLength(1);
    await expect(marked.querySelector('[data-next-summary-holds]')).toHaveTextContent(
      `${SUMMARY_HOLDS}Departure · Goal`,
    );
    await userEvent.click(
      within(marked).getByRole('button', { name: 'Departure · Goal, go to the card' }),
    );
    const departure = canvasElement.querySelector<HTMLElement>('[data-next-departure="goal"]');
    await waitFor(() => expect(departure?.contains(document.activeElement)).toBe(true));
    const back = departure?.querySelector<HTMLElement>('[data-next-departure-summary="phase"]');
    await expect(back).toHaveTextContent(`In What the session has done:${SECOND_PHASE.title}`);
    await userEvent.click(
      within(back as HTMLElement).getByRole('button', {
        name: `Go to the summary phase that holds this evidence: ${SECOND_PHASE.title}`,
      }),
    );
    await waitFor(() => expect(document.activeElement).toBe(within(marked).getByRole('heading')));
  },
};

/* Two phases whose cited spans both hold the departure's check are both marked, and the card links to each. */
export const DepartureMarksTwoPhases: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [FIRST_PHASE]),
          block('p2', 'a3', 4, [
            {
              title: 'Leaving the tests alone',
              bullets: [bullet('Asked to leave the tests alone.', 'asked', ['p2', 'a3'])],
            },
            {
              title: 'Reverting and checking',
              bullets: [bullet('Reverting the test edit.', 'said', ['a2', 'a3'])],
            },
          ]),
        ],
      })}
      session={departureReading(['c3'])}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await waitFor(() =>
      expect(
        [...summary.querySelectorAll<HTMLElement>('[data-next-summary-marked]')].map(
          (node) => node.dataset['nextSummaryPhase'],
        ),
      ).toEqual(['1:0', '1:1']),
    );
    const back = canvasElement.querySelector(
      '[data-next-departure-summary="phase"]',
    ) as HTMLElement;
    await expect(within(back).getAllByRole('button')).toHaveLength(2);
  },
};

/* A departure with no matching phase says where its evidence sits, from the summary's coverage. */
function unmatched(
  name: string,
  summary: Record<string, unknown>,
  where: keyof typeof PLACE_LINES,
) {
  return {
    name,
    render: () => <SummaryPage summary={summary} session={departureReading(['c3'])} />,
    play: async ({ canvasElement }: { canvasElement: HTMLElement }) => {
      const line = await waitFor(() => {
        const node = canvasElement.querySelector<HTMLElement>('[data-next-departure-summary]');
        if (!node) throw new Error('no summary line on the departure');
        return node;
      });
      await expect(line.dataset['nextDepartureSummary']).toBe(where);
      await expect(line).toHaveTextContent(`In What the session has done:${PLACE_LINES[where]}`);
      await expect(canvasElement.querySelector('[data-next-summary-marked]')).toBeNull();
    },
  } satisfies Story;
}

export const DepartureAfterTheSummary = unmatched(
  'Departure after the last summarized entry',
  storedSummary({ blocks: [block('p1', 'c2', 4, [FIRST_PHASE])] }),
  'after',
);
export const DepartureBeforeTheSummary = unmatched(
  'Departure before where the summary starts',
  storedSummary({
    starts_at: 'a3',
    blocks: [
      gap('p1', 'c3', 7, 'before_window'),
      block('a3', 'a3', 1, [
        {
          title: 'Restoring the tests',
          bullets: [bullet('Said it is restoring the tests.', 'said', ['a3'])],
        },
      ]),
    ],
  }),
  'before',
);
export const DepartureInAGap = unmatched(
  'Departure inside a part that could not be summarized',
  storedSummary({
    blocks: [block('p1', 'c2', 4, [FIRST_PHASE]), gap('p2', 'a3', 4, 'no_output')],
  }),
  'gap',
);
export const DepartureInNoPhase = unmatched(
  'Departure inside the span but in no phase',
  storedSummary({
    blocks: [
      block('p1', 'c2', 4, [FIRST_PHASE]),
      block('p2', 'a3', 4, [
        {
          title: 'Leaving the tests alone',
          bullets: [bullet('Asked to leave the tests alone.', 'asked', ['p2'])],
        },
        {
          title: 'Restoring the test file',
          bullets: [bullet('Said the test file is restored.', 'said', ['a3'])],
        },
      ]),
    ],
  }),
  'between',
);

/* A reading out of date, or marked not accurate, marks nothing. */
export const StaleReadingMarksNothing: Story = {
  render: () => (
    <SummaryPage
      summary={withCheck()}
      session={departureReading(['c3'], { annotation_revision: 4 })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-result-stale]')).not.toBeNull(),
    );
    await expect(region.querySelector('[data-next-summary-marked]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-departure-summary]')).toBeNull();
  },
};
export const InaccurateReadingMarksNothing: Story = {
  render: () => (
    <SummaryPage
      summary={withCheck()}
      session={departureReading(['c3'], { annotation_not_accurate: true })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-departure="goal"]')).not.toBeNull(),
    );
    await expect(region.querySelector('[data-next-summary-marked]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-departure-summary]')).toBeNull();
  },
};

/* A cold reopen: the first phase cites an entry no loaded page holds, and its chip reads older pages for it. */
export const ColdReopenCitesAnOlderPage: Story = {
  render: () => <SummaryPage summary={storedSummary()} paged />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const chip = summary.querySelector<HTMLElement>(
      '[data-next-summary-phase="0:0"] [data-next-outline-entry="p1"]',
    ) as HTMLElement;
    await expect(chip).toHaveAccessibleName(
      'Open an older entry the page has not read yet, cited for “You asked for retry with backoff on the webhook handler.”, in Full activity',
    );
    await expect(entryRow(canvasElement, 'p1')).toBeNull();
    await seeInContext(chip);
    await waitFor(() => expect(document.activeElement).toBe(entryRow(canvasElement, 'p1')));
    await expect(region.querySelector('[data-next-outline-missing]')).toBeNull();
  },
};

/* A chip whose entry no page holds says it could not be loaded. */
export const CitationThatCannotLoad: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Reading the handler',
              bullets: [bullet('Asked about a missing entry.', 'asked', ['p9'])],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await seeInContext(
      within(summary).getByRole('link', {
        name: /^Open an older entry the page has not read yet, cited for “You asked about a missing entry\.”/,
      }),
    );
    await waitFor(() =>
      expect(region.querySelector('[data-next-outline-missing]')).toHaveTextContent(
        'Full activity does not show that entry: it could not be loaded',
      ),
    );
  },
};

/* A summary that lands while the reader is editing the goal leaves focus and the edit where they were. */
export const LandsDuringAnEdit: Story = {
  render: () => <SummaryPage summary={ABSENT} ended={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await stateOf(region, 'none');
    const goal = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLTextAreaElement>('textarea');
      if (!node) throw new Error('no goal box');
      return node;
    });
    await userEvent.click(goal);
    await userEvent.type(goal, ' and keep it small');
    const typed = goal.value;
    const caret = goal.selectionStart;
    script.summary = storedSummary();
    await poll();
    await summaryOf(region);
    await frames();
    await expect(document.activeElement).toBe(goal);
    await expect(goal.value).toBe(typed);
    await expect(goal.selectionStart).toBe(caret);
  },
};

const advance = (ms: number) => {
  if (!script.shell) throw new Error('no shell yet');
  (script.shell.clock as FakeClock).advance(ms);
};
const deletePosts = () => script.posts.filter((post) => post.path === '/api/summary/delete');

/* The first press on Delete summary deletes nothing: it says what will go and what will not, and the offer
   lapses on its own, said in seconds. */
export const DeleteAsksFirst: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await userEvent.click(within(region).getByRole('button', { name: 'Delete summary' }));
    const confirm = await within(region).findByRole('button', { name: 'Confirm delete' });
    await expect(deletePosts()).toEqual([]);
    await expect(region.querySelector('[data-next-summary-delete-armed]')).toHaveTextContent(
      'Nothing has been deleted yet, and this offer lapses in 30 seconds.',
    );
    await expect(confirm).toHaveAttribute('aria-describedby', 'next-summary-delete-armed');
    // A press inside the dwell is another arm and never the deletion.
    await userEvent.click(confirm);
    await expect(deletePosts()).toEqual([]);
    await expect(region.querySelector('[data-next-summary]')).not.toBeNull();
    // Keep summary takes the offer back, and the next press arms again.
    await userEvent.click(within(region).getByRole('button', { name: 'Keep summary' }));
    await expect(within(region).getByRole('button', { name: 'Delete summary' })).toBeVisible();
    await userEvent.click(within(region).getByRole('button', { name: 'Delete summary' }));
    await within(region).findByRole('button', { name: 'Confirm delete' });
    advance(31_000);
    await waitFor(() =>
      expect(within(region).queryByRole('button', { name: 'Confirm delete' })).toBeNull(),
    );
    await expect(within(region).getByRole('button', { name: 'Delete summary' })).toBeVisible();
    await expect(deletePosts()).toEqual([]);
  },
};

/* Delete summary removes it after a second press, says so with the time, and does not summarize the session
   again on this open. */
export const DeleteDoesNotRestart: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    script.answer = (path, body) => {
      if (path === '/api/summary/delete') script.summary = ABSENT;
      return defaultAnswer(path, body);
    };
    await userEvent.click(within(region).getByRole('button', { name: 'Delete summary' }));
    await within(region).findByRole('button', { name: 'Confirm delete' });
    advance(1_300);
    await userEvent.click(within(region).getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(region.querySelector('[data-next-summary]')).toBeNull());
    await poll();
    await expect(script.posts).toEqual([
      { path: '/api/summary/delete', body: { harness: 'claude', sid: 's1' } },
    ]);
    const line = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-summary-deleted]');
      if (!node) throw new Error('no result line yet');
      return node;
    });
    await expect(line).toHaveTextContent(
      /^Summary deleted at \d{2}:\d{2}\. Summarize writes a new one\.$/,
    );
    // Summarize is the way to a new one, and pressing it takes the line down.
    await userEvent.click(within(region).getByRole('button', { name: 'Summarize' }));
    await waitFor(() => expect(region.querySelector('[data-next-summary-deleted]')).toBeNull());
  },
};

/* The view-only sample draws a stored summary its fixture carries, keeps its citations live, and holds every
   summary control, as it holds every other write. */
function SampleWithSummary() {
  const [shell] = useState(() =>
    createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(fakeRouterEnvironment(SAMPLE_FRAGMENT).env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          new Response(JSON.stringify(url.startsWith('/api/data') ? { sessions: [] } : {}), {
            status: 200,
          }),
        ),
    }),
  );
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  const context = SAMPLE_FIXTURE.context as Record<string, Record<string, unknown>>;
  const fixture = {
    ...SAMPLE_FIXTURE,
    board: { ...SAMPLE_FIXTURE.board, summaries: grant() },
    context: {
      ...context,
      sources: {
        ...context['sources'],
        summary: storedSummary({
          lede: {
            text: 'The agent coordinated other agents on the milestone.',
            cites: [SAMPLE_SAID],
          },
          blocks: [
            block(SAMPLE_PHASE_START, SAMPLE_SAID, 3, [
              {
                title: 'Looking into the refused reading',
                bullets: [
                  bullet('Said it would check the merge order first.', 'said', [
                    SAMPLE_PHASE_START,
                  ]),
                ],
              },
            ]),
          ],
        }),
      },
    },
  };
  return (
    <SampleFixtureContext value={fixture}>
      <App shell={shell} />
    </SampleFixtureContext>
  );
}

/* Two of the sample's agent messages on the newest record page (#81 and #79), so a chip lands without reading an
   older page. */
const SAMPLE_PHASE_START = 'fact:d5e713ad0690df2d';
const SAMPLE_SAID = 'fact:8d9a97cc2010ab9e';

export const SampleDrawsAStoredSummary: Story = {
  render: () => <SampleWithSummary />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(within(summary).getByRole('heading', { level: 3 })).toHaveTextContent(
      'Looking into the refused reading',
    );
    await attributed(summary);
    // The sample holds a stored summary, so its open posts nothing, and the controls are held.
    await userEvent.click(within(region).getByRole('button', { name: 'Delete summary' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-sample-held]')).toHaveTextContent(
        'View only: this sample cannot be edited, saved or run.',
      ),
    );
    await expect(region.querySelector('[data-next-summary]')).not.toBeNull();
    // A citation reads: it lands on its entry in Full activity.
    const chip = summary.querySelector<HTMLElement>(
      `[data-next-summary-phase="0:0"] [data-next-outline-entry="${SAMPLE_PHASE_START}"]`,
    ) as HTMLElement;
    await seeInContext(chip);
    await waitFor(() =>
      expect(document.activeElement).toBe(entryRow(canvasElement, SAMPLE_PHASE_START)),
    );
  },
};

const consent = (on: boolean) => ({ path: '/api/summary', body: { consent: on ? 'on' : 'off' } });
const openPosts = () => summaryPosts().filter((post) => post.body['origin'] === 'open');

/* The off switch is one press from the card while a job runs and no notice is drawn. */
export const TurnOffWhileWorking: Story = {
  render: () => <SummaryPage summary={{ ...ABSENT, job: job({ part: 1 }) }} ended={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const working = await stateOf(region, 'working');
    await expect(working.querySelector('[data-next-summary-notice]')).toBeNull();
    await userEvent.click(within(working).getByRole('button', { name: 'Turn off summaries' }));
    await waitFor(() => expect(script.posts).toEqual([consent(false)]));
  },
};

/* At the cap, Turn off is one press away; turning summaries back on after the cap posts only the consent, never
   the open's summary. */
export const CapTurnOffThenOn: Story = {
  render: () => <SummaryPage summary={ABSENT} grant={grant({ reason: 'daily-cap', used: 200 })} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const blocked = await stateOf(region, 'blocked');
    await userEvent.click(within(blocked).getByRole('button', { name: 'Turn off summaries' }));
    const off = await stateOf(region, 'off');
    await poll();
    await userEvent.click(within(off).getByRole('button', { name: 'Turn summaries on' }));
    await stateOf(region, 'none');
    await poll();
    await poll();
    await expect(script.posts).toEqual([consent(false), consent(true)]);
  },
};

/* Off at the cap: the server names the cap as the reason, and the card still draws off with Turn summaries on,
   the cap said beneath it. */
export const OffAtTheCap: Story = {
  render: () => (
    <SummaryPage
      summary={ABSENT}
      grant={grant({ consent: false, off: true, reason: 'daily-cap', used: 200 })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const off = await stateOf(region, 'off');
    await expect(off).toHaveTextContent(SUMMARY_OFF);
    await expect(off.querySelector('[data-next-summary-reason="daily-cap"]')).toHaveTextContent(
      /^Summaries have used their 200 model calls/,
    );
    await expect(within(off).getByRole('button', { name: 'Turn summaries on' })).toBeVisible();
    await expect(within(off).queryByRole('button', { name: 'Turn off summaries' })).toBeNull();
    await poll();
    await expect(script.posts).toHaveLength(0);
  },
};

/* A saved summary while summaries are off: what is sent offers Turn summaries on, never Turn off. */
export const SentWhileOff: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary()}
      grant={grant({ consent: false, off: true, reason: 'summaries-off' })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await userEvent.click(
      within(summary).getByRole('button', { name: 'What is sent to Claude Code' }),
    );
    // The off state's own Turn summaries on, and the one inside what is sent.
    await waitFor(() =>
      expect(
        within(document.body).getAllByRole('button', { name: 'Turn summaries on' }),
      ).toHaveLength(2),
    );
    await expect(
      within(document.body).queryByRole('button', { name: 'Turn off summaries' }),
    ).toBeNull();
    await userEvent.keyboard('{Escape}');
  },
};

/* The open is decided once: a session that ends while it is open is not summarized on this page load. */
export const EndsWhileOpen: Story = {
  render: () => <SummaryPage summary={ABSENT} ended={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await stateOf(region, 'none');
    await poll();
    script.session = { state: 'idle', ended_at: 1 };
    await poll();
    await poll();
    await expect(within(region).getByRole('button', { name: 'Summarize' })).toBeVisible();
    await expect(openPosts()).toEqual([]);
    await expect(script.posts).toEqual([]);
  },
};

/* A cap that lifts while the finished session is open does not summarize it on this page load. */
export const CapLiftsWhileOpen: Story = {
  render: () => <SummaryPage summary={ABSENT} grant={grant({ reason: 'daily-cap', used: 200 })} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await stateOf(region, 'blocked');
    await poll();
    script.grant = grant();
    await poll();
    await stateOf(region, 'none');
    await poll();
    await expect(script.posts).toEqual([]);
  },
};

/* A summary deleted in another tab leaves this one with none, and this open does not make another. */
export const DeletedInAnotherTab: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    script.summary = ABSENT;
    await poll();
    await stateOf(region, 'none');
    await poll();
    await expect(script.posts).toEqual([]);
  },
};

/* A summary left partway by a cancel compares as unchanged, and still offers Summarize again for the rest,
   keeping the saved summary drawn until a new one is published. */
export const IncompleteOffersSummarizeAgain: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        state: 'partial',
        lede: null,
        lede_reason: 'stopped',
        blocks: [block('p1', 'c2', 4, [FIRST_PHASE]), gap('p2', 'a2', 2, 'stopped')],
        job: job({ state: 'cancelled', reason: 'cancelled', parts: 2, finished_parts: [1] }),
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const line = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-summary-incomplete]');
      if (!node) throw new Error('no Summarize again for the rest');
      return node;
    });
    await expect(line).toHaveTextContent(SUMMARY_INCOMPLETE);
    await expect(region.querySelector('[data-next-summary-outdated]')).toBeNull();
    for (const width of [1280, 400])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
    await userEvent.click(within(line).getByRole('button', { name: 'Summarize again' }));
    await waitFor(() =>
      expect(summaryPosts()).toEqual([
        {
          path: '/api/summary',
          body: { harness: 'claude', sid: 's1', action: 'rerun', origin: 'press' },
        },
      ]),
    );
    await expect(summary.isConnected).toBe(true);
    await expect(summary.querySelector('[data-next-summary-phase="0:0"]')).not.toBeNull();
  },
};

/* An asked bullet that opens with another speech verb still names the person, in its text and its chip. */
export const AskedNamesThePerson: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Agreeing the scope',
              bullets: [bullet('Confirmed the parser change is in scope.', 'asked', ['p1'])],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await openPhases(summary);
    const row = summary.querySelector('[data-next-summary-bullet="asked"]') as HTMLElement;
    await expect(row.querySelector('[data-next-summary-text]')).toHaveTextContent(
      'You said: Confirmed the parser change is in scope.',
    );
    await waitFor(() =>
      expect(
        within(row).getByRole('link', {
          name: /cited for “You said: Confirmed the parser change is in scope\.”/,
        }),
      ).toBeVisible(),
    );
    await attributed(summary);
  },
};

/* A failed check whose text names no failure is told apart from work in words, in its text and its chip. */
export const FailedSaysSoInWords: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Running the webhook tests',
              bullets: [
                bullet('Ran pytest tests/test_webhook.py.', 'failed', ['c1']),
                bullet({ withheld: true, reason: 'too_long_cut' }, 'failed', ['c1']),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await openPhases(summary);
    const [shownRow, withheldRow] = [
      ...summary.querySelectorAll<HTMLElement>('[data-next-summary-bullet="failed"]'),
    ];
    await expect(shownRow?.querySelector('[data-next-summary-text]')).toHaveTextContent(
      'Failed as the tool reported: Ran pytest tests/test_webhook.py.',
    );
    await waitFor(() =>
      expect(
        within(shownRow as HTMLElement).getByRole('link', {
          name: /cited for “Failed as the tool reported: Ran pytest/,
        }),
      ).toBeVisible(),
    );
    // A withheld line carries no result label: "Failed as the tool reported: Left out: ..." put a result on
    // words nobody can see.
    await expect(withheldRow).toBeUndefined();
    const hidden = summary.querySelector('[data-next-summary-hidden]') as HTMLElement;
    await expect(hidden.querySelector('[data-next-summary-hidden-line]')).toHaveTextContent(
      /^1 line hidden: it was too long to show whole\./,
    );
    await expect(hidden).not.toHaveTextContent(/Failed/);
  },
};

/* An asked line whose words report the agent reads as the agent's, never "You said: The agent said ...". */
export const AgentWordsOnAnAskedLine: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Agreeing the scope',
              bullets: [
                bullet('The agent said it also raised the billing rate.', 'asked', ['p1', 'a1']),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const row = summary.querySelector('[data-next-summary-bullet="asked"]') as HTMLElement;
    await expect(row.querySelector('[data-next-summary-text]')).toHaveTextContent(
      'The agent said it also raised the billing rate.',
    );
    await expect(row).not.toHaveTextContent(/You said/);
    await waitFor(() =>
      expect(
        within(row).getAllByRole('link', {
          name: /cited for “The agent said it also raised the billing rate\.”/,
        }),
      ).toHaveLength(2),
    );
  },
};

/* A run of withheld lines in a phase is one muted line saying how many, why and which entries, with each line's
   reason and citations one press away; a line kept between two runs splits them. */
export const WithheldRunCollapses: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Adding retry to the webhook handler',
              bullets: [
                bullet({ withheld: true, reason: 'completion_claim' }, 'did', ['a1']),
                bullet({ withheld: true, reason: 'completion_claim' }, 'failed', ['c1']),
                bullet('Asked for retry with backoff on the webhook handler.', 'asked', ['p1']),
                bullet({ withheld: true, reason: 'no_citation' }, 'did', []),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await openPhases(summary);
    const runs = [...summary.querySelectorAll<HTMLElement>('[data-next-summary-hidden]')];
    await expect(runs.map((run) => run.dataset['nextSummaryHidden'])).toEqual(['2', '1']);
    const [first, second] = runs as [HTMLElement, HTMLElement];
    await waitFor(() =>
      expect(first.querySelector('[data-next-summary-hidden-line]')).toHaveTextContent(
        '2 lines were left out because the record does not back them. Entries #2 to #2.1.',
      ),
    );
    await expect(second.querySelector('[data-next-summary-hidden-line]')).toHaveTextContent(
      '1 line hidden: it cited no entry.',
    );
    // Muted, and no result label even on the withheld failed line.
    await expect(first).not.toHaveTextContent(/^Failed/);
    await expect(getComputedStyle(first).color).not.toBe('rgb(228, 136, 106)');
    // Each hidden line's own reason and citations, reachable from the keyboard.
    const why = within(first).getByRole('button', { name: 'Why each was hidden' });
    why.focus();
    await userEvent.keyboard('{Enter}');
    const reasons = [...first.querySelectorAll<HTMLElement>('ol [data-next-summary-withheld]')];
    await expect(reasons).toHaveLength(2);
    await expect(why).toHaveAttribute('aria-expanded', 'true');
    for (const reason of reasons) {
      await waitFor(() => expect(reason).toBeVisible());
      await expect(reason).toHaveTextContent(WITHHELD_LINES.completion_claim ?? '');
    }
    await waitFor(() =>
      expect(
        within(first).getByRole('link', { name: /^Open entry #2\.1, cited for a hidden line/ }),
      ).toBeVisible(),
    );
    await expect(summary.querySelectorAll('[data-next-summary-bullet]')).toHaveLength(1);
    for (const width of [1280, 400])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
  },
};

/* Full activity: where each entry came from is one press away in its head, not a sentence read out on every
   row, and the header names the token rate's unit. */
export const FullActivitySourceOnePressAway: Story = {
  render: () => <SummaryPage summary={storedSummary()} session={{ rate_per_min: 44 }} />,
  play: async ({ canvasElement }) => {
    await card(canvasElement);
    await userEvent.click(
      await within(canvasElement).findByRole('button', { name: 'Full activity' }),
    );
    const entry = await waitFor(() => {
      const node = entryRow(canvasElement, 'a1');
      if (!node) throw new Error('no row yet');
      return node as HTMLElement;
    });
    await expect(entry.querySelector('.next-visually-hidden.next-cockpit-work-source')).toBeNull();
    const source = within(entry).getByRole('button', { name: 'Source of entry #2' });
    await expect(source.closest('.next-cockpit-work-head')).not.toBeNull();
    const panel = document.getElementById(source.getAttribute('aria-controls') ?? '');
    await expect(panel?.hidden).toBe(true);
    await userEvent.click(source);
    await expect(source).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(panel).toBeVisible());
    await expect(panel).toHaveTextContent('transcript · exact');
    const identity = canvasElement.querySelector('.next-session-identity');
    await expect(identity?.textContent ?? '').not.toMatch(/\d \/m\b/);
  },
};

/* After the intent is saved, an entry before its window keeps its number on a chip, muted, with the reason, and
   the header keeps the session's count: once they turned to the bare word "entry" and "4 entries" to "2". */
export const SavedIntentKeepsEarlierNumbers: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary()}
      session={{ annotation_window_start: G - 400, annotation_goal_saved_at: G - 400 }}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const earlier = await waitFor(() => {
      const chip = summary.querySelector<HTMLElement>('[data-next-outline-entry="a1"]');
      if (!chip?.textContent?.startsWith('[')) throw new Error('no number yet');
      return chip;
    });
    await expect(earlier).toHaveTextContent('[2]');
    await expect(earlier.hasAttribute('data-next-entry-outside')).toBe(true);
    await expect(earlier.getAttribute('aria-label')).toContain(OUTSIDE_WINDOW);
    const inside = summary.querySelector<HTMLElement>('[data-next-outline-entry="p2"]');
    await expect(inside?.hasAttribute('data-next-entry-outside')).toBe(false);
    for (const chip of summary.querySelectorAll('[data-next-outline-entry]'))
      await expect(chip.textContent).not.toBe('entry');
    await userEvent.hover(earlier);
    await expect(await within(document.body).findByRole('tooltip')).toHaveTextContent(
      OUTSIDE_WINDOW,
    );
    await expect(canvasElement.querySelector('.next-session-detail-meta')).toHaveTextContent(
      /\b\d+ entries, \d+ since your intent’s start/,
    );
  },
};

/* A chip never reads as the bare word "entry". With counted numbers an entry before the intent's window has no
   number to keep, and a message the page has not read yet has none until its page arrives: each chip says which. */
export const UnnumberedChipsSayWhy: Story = {
  render: () => (
    <SummaryPage
      counted
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              ...FIRST_PHASE,
              bullets: [
                ...FIRST_PHASE.bullets,
                bullet('Asked to start from the last release.', 'asked', ['p-unread']),
              ],
            },
          ]),
          block('p2', 'a2', 2, [SECOND_PHASE]),
        ],
      })}
      session={{ annotation_window_start: G - 400, annotation_goal_saved_at: G - 400 }}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const earlier = await waitFor(() => {
      const chip = summary.querySelector<HTMLElement>('[data-next-outline-entry="a1"]');
      if (!chip?.hasAttribute('data-next-entry-outside')) throw new Error('not outside yet');
      return chip;
    });
    await expect(earlier).toHaveTextContent('[?]');
    await expect(earlier.getAttribute('aria-label')).toContain('before your intent’s start');
    const unread = summary.querySelector<HTMLElement>('[data-next-outline-entry="p-unread"]');
    await expect(unread).toHaveTextContent('[?]');
    await expect(unread?.getAttribute('aria-label')).toContain('the page has not read yet');
    for (const chip of region.querySelectorAll('[data-next-outline-entry]')) {
      await expect(chip.textContent).not.toBe('entry');
      if (!/^[#[]/.test(chip.textContent ?? ''))
        await expect(chip.hasAttribute('data-next-entry-unnumbered')).toBe(true);
    }
    for (const width of [1280, 400])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
  },
};

/* A summary citing a check under the source's own id, which the record does not carry: the bullet gets no
   chip that would read pages to the cap, says the citation cannot be opened from here, and the departure the
   check is evidence for is not placed where Compass cannot stand behind it. */
export const CheckCitationTheRecordDoesNotCarry: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [FIRST_PHASE]),
          block('p2', 'source-check-9', 4, [
            {
              title: 'Checking the webhook',
              bullets: [
                bullet('Asked to keep the diff small.', 'asked', ['p2']),
                bullet(
                  'pytest tests/test_webhook.py reported failed, as the tool reported.',
                  'failed',
                  ['source-check-9'],
                ),
              ],
            },
          ]),
        ],
      })}
      session={departureReading(['c3'])}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const row = await waitFor(() => {
      const rows = summary.querySelectorAll<HTMLElement>('[data-next-summary-bullet="failed"]');
      const last = rows[rows.length - 1];
      if (!last) throw new Error('no failed bullet');
      return last;
    });
    await expect(row.querySelector('[data-next-outline-entry]')).toBeNull();
    // Said once, at the foot of the card, and not after the line that cites it.
    await expect(row.querySelector('[data-next-summary-unlinked]')).toBeNull();
    await expect(summary.querySelectorAll('[data-next-summary-unlinked]')).toHaveLength(1);
    await expect(summary.querySelector('[data-next-summary-unlinked]')).toHaveTextContent(
      '1 cited entry is an earlier check or file that Full activity does not list, so it cannot be opened from here.',
    );
    const line = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-departure-summary]');
      if (!node) throw new Error('no summary line on the departure');
      return node;
    });
    await expect(line.dataset['nextDepartureSummary']).toBe('unplaced');
    await expect(line).toHaveTextContent(PLACE_LINES.unplaced);
    await expect(summary.querySelector('[data-next-summary-marked]')).toBeNull();
  },
};

/* Hostile text: a tick the server let through, and a kind the card does not know, are withheld in place. */
export const HostileTickAndKind: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        lede: { text: 'The retry handler ✅', cites: ['p1'] },
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Retry handler ✔️',
              bullets: [
                bullet('Added the retry handler ✓', 'did', ['c1']),
                bullet('Said the parser is fixed', 'verdict', ['a1']),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(
      summary.querySelectorAll('[data-next-summary-withheld="completion_claim"]'),
    ).toHaveLength(3);
    await expect(
      summary.querySelector('[data-next-summary-withheld="shape_fault"]'),
    ).toHaveTextContent(WITHHELD_LINES.shape_fault ?? '');
    await expect(summary).not.toHaveTextContent('Said the parser is fixed');
    await neverDone(region);
  },
};

/* A cut citation list and a cut reply are each said where they stand. */
export const CutsAreSaid: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          {
            ...block('p1', 'c2', 4, [
              {
                ...FIRST_PHASE,
                bullets: [{ ...bullet('Asked for retry.', 'asked', ['p1']), cites_cut: 2 }],
              },
            ]),
            cut: { phases: 0, reply: true },
          },
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(summary.querySelector('[data-next-summary-cites-cut="2"]')).toHaveTextContent(
      '2 more citations were cut',
    );
    await expect(summary.querySelector('[data-next-summary-reply-cut]')).toHaveTextContent(
      REPLY_CUT,
    );
  },
};

/* A lost reply says the request is unconfirmed, not that nothing changed, and still asks for the next board. */
export const LostReplyAsksTheBoard: Story = {
  render: () => (
    <SummaryPage summary={ABSENT} ended={false} answer={() => ({ status: 0, body: {} })} />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const none = await stateOf(region, 'none');
    const before = script.boards;
    await userEvent.click(within(none).getByRole('button', { name: 'Summarize' }));
    await waitFor(() =>
      expect(region.querySelector('[data-next-summary-failed]')).toHaveTextContent(
        SUMMARY_FAILED_SEND,
      ),
    );
    await expect(region).not.toHaveTextContent('Nothing changed');
    await waitFor(() => expect(script.boards).toBeGreaterThan(before));
  },
};

/* A chip pressed in the outline under a saved summary says it could not be shown inside the outline, where the
   press was made, not above the summary. The outline's failed check is from before the intent's start, which Full
   activity does not list. */
export const MissingLineStaysInTheOutline: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary()}
      outline={claudeOutline({}, true)}
      session={{ annotation_window_start: G - 400, annotation_goal_saved_at: G - 400 }}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await summaryOf(region);
    await userEvent.click(
      within(region).getByRole('button', { name: "Compass's outline of this session" }),
    );
    const outline = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-outline="blocks"]');
      if (!node) throw new Error('no outline');
      return node;
    });
    const chip = await waitFor(() => {
      const node = outline.querySelector<HTMLElement>('[data-next-outline-entry="c1"]');
      if (!node) throw new Error('no chip yet');
      return node;
    });
    await userEvent.click(chip);
    await waitFor(() =>
      expect(outline.querySelector('[data-next-outline-missing]')).not.toBeNull(),
    );
    await expect(region.querySelectorAll('[data-next-outline-missing]')).toHaveLength(1);
  },
};

/* The phases arrive open, so the opening and its bullets are in view with no press: the design shows the story, not
   a column of closed headings. A reader who closes one keeps it closed through the next board. */
export const BulletsInViewOnFirstRender: Story = {
  render: () => <SummaryPage summary={storedSummary()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const phases = [...summary.querySelectorAll<HTMLElement>('[data-next-summary-phase]')];
    await expect(phases).toHaveLength(2);
    for (const phase of phases) {
      await expect(phase.querySelector('[data-slot="accordion-trigger"]')).toHaveAttribute(
        'aria-expanded',
        'true',
      );
      const bullets = [...phase.querySelectorAll<HTMLElement>('[data-next-summary-bullet]')];
      await expect(bullets.length).toBeGreaterThan(0);
      for (const bullet of bullets) await waitFor(() => expect(bullet).toBeVisible());
    }
    const trigger = phases[0]?.querySelector('[data-slot="accordion-trigger"]') as HTMLElement;
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await poll();
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(phases[1]?.querySelector('[data-slot="accordion-trigger"]')).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  },
};

/* The citations Full activity does not list are said once, at the foot of the card, as a count of the entries
   across the opening and every line: they were said after the opening and most bullets. */
export const FullActivityLimitSaidOnce: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        lede: { text: LEDE, cites: ['source-check-8', 'p1'] },
        blocks: [
          block('p1', 'source-check-9', 4, [
            {
              title: 'Running the webhook checks',
              bullets: [
                bullet('The agent ran pytest tests/test_webhook.py.', 'did', ['source-check-8']),
                bullet('The agent ran pytest tests/test_retry.py.', 'did', ['source-check-9']),
                bullet(
                  'pytest tests/test_webhook.py reported failed, as the tool reported.',
                  'failed',
                  ['source-check-9'],
                ),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const notes = summary.querySelectorAll<HTMLElement>('[data-next-summary-unlinked]');
    await expect(notes).toHaveLength(1);
    const note = notes[0] as HTMLElement;
    await expect(note).toHaveTextContent(
      '2 cited entries are earlier checks or files that Full activity does not list, so they cannot be opened from here.',
    );
    await expect(note.dataset['nextSummaryUnlinked']).toBe('2');
    // Not after the opening, nor after a bullet.
    await expect(
      summary.querySelector('[data-next-summary-lede] [data-next-summary-unlinked]'),
    ).toBeNull();
    for (const row of summary.querySelectorAll('[data-next-summary-bullet]'))
      await expect(row.querySelector('[data-next-summary-unlinked]')).toBeNull();
    // At the foot: after the last line the summary draws.
    const last = [...summary.querySelectorAll('[data-next-summary-bullet]')].at(-1) as Element;
    await expect(
      last.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  },
};

/* The badge on a phase counts failed test runs. A build that failed, or a browser run the agent's sandbox
   refused, is still drawn as a failed line, and is not counted as a test failure. */
export const OnlyTestFailuresAreBadged: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        blocks: [
          block('p1', 'c2', 4, [
            {
              title: 'Running the tests',
              bullets: [
                bullet('pnpm test:stories reported failed, as the tool reported.', 'failed', [
                  'c1',
                ]),
                bullet(
                  'The Storybook browser run reported failed, as the tool reported, and the agent attributed the launch error to the sandbox.',
                  'failed',
                  ['c2'],
                ),
              ],
            },
            {
              title: 'Building the page',
              bullets: [
                bullet('pnpm build reported failed, as the tool reported.', 'failed', ['c2']),
              ],
            },
          ]),
        ],
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    const [tests, build] = [...summary.querySelectorAll<HTMLElement>('[data-next-summary-phase]')];
    await expect(tests?.querySelector('[data-next-summary-failures]')).toHaveTextContent(
      /^1 test failure$/,
    );
    await expect(build?.querySelector('[data-next-summary-failures]')).toBeNull();
    // The failed lines are all still said.
    await expect(summary.querySelectorAll('[data-next-summary-bullet="failed"]')).toHaveLength(3);
  },
};

/* A summary written again can group the work differently, and says so while it is being written, and no longer
   once the rerun is over: the note was held from the press until the page reloaded, and drew again under the
   next update. A first summary says nothing of the kind. */
export const RewrittenSummaryNotes: Story = {
  render: () => (
    <SummaryPage
      summary={storedSummary({
        out_of_date: {
          kind: 'changed_earlier',
          reason: 'changed_earlier',
          affected_blocks: [0],
          new_entries: 0,
          appendable: false,
          action: 'summarize_again',
        },
      })}
    />
  ),
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(summary.querySelector('[data-next-summary-rewritten]')).toBeNull();
    await userEvent.click(await within(region).findByRole('button', { name: 'Summarize again' }));
    await waitFor(() =>
      expect(summary.querySelector('[data-next-summary-rewritten]')).toHaveTextContent(
        'A summary written again can group the work into different phases from the one before.',
      ),
    );
    // The rerun finishes: the server's job is complete, and the note goes.
    script.summary = { ...(script.summary ?? {}), job: job({ state: 'complete' }) };
    await poll();
    await waitFor(() => expect(summary.querySelector('[data-next-summary-rewritten]')).toBeNull());
  },
};
