import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { SAMPLE_FIXTURE, SampleFixtureContext } from '../src/sample/fixture';
import { SAMPLE_FRAGMENT } from '../src/sample/ids';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import {
  FRESHNESS_UNKNOWN,
  GAP_RUNNING,
  PLACE_LINES,
  REPLY_CUT,
  SUMMARY_ADDS,
  SUMMARY_FAILED_SEND,
  SUMMARY_HOLDS,
  SUMMARY_INCOMPLETE,
  SUMMARY_LABEL,
  SUMMARY_OFF,
  SUMMARY_WORKING_KEEP,
  WITHHELD_LINES,
} from '../src/sessions/summary';
import { neverDone, noCheckMark } from './drift.checks';
import { claudeOutline } from './outline.scenario';
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

/* Each `said` bullet opens with "Said" and cites only the agent's messages; each `asked` opens with "You" and
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
    if (kind === 'said') await expect(words).toMatch(/^Said\b/);
    if (kind === 'asked') await expect(words).toMatch(/^You (asked|said)\b/);
    if (kind === 'failed') await expect(words).toMatch(/^Failed as the tool reported: /);
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
      if (entry) await expect(chip.textContent).toMatch(/^#\d+(\.\d+)?$/);
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
    await expect(summary.querySelector('[data-next-summary-lede]')).toHaveTextContent(LEDE);
    const headings = within(summary).getAllByRole('heading', { level: 3 });
    await expect(headings.map((node) => node.textContent)).toEqual([
      FIRST_PHASE.title,
      SECOND_PHASE.title,
    ]);
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^claude-sonnet-5-5 · summarized at \d\d:\d\d$/,
    );
    await waitFor(() =>
      expect(summary.querySelector('[data-next-outline-entry="a1"]')).toHaveTextContent('#2'),
    );
    await attributed(summary);
    // The model wrote "Reverting the test edit." for a `said` bullet: it is drawn as the agent's words.
    await expect(summary).toHaveTextContent('Said: Reverting the test edit.');
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
    await expect(summary.querySelectorAll('a, strong, em, code, img')).toHaveLength(0);
    // A chip opens Full activity at its entry.
    await userEvent.click(
      within(summary).getByRole('button', { name: /^Open entry #2\.1, cited for/ }),
    );
    await waitFor(() => expect(document.activeElement).toBe(entryRow(canvasElement, 'c1')));
    await expect(summaryPosts()).toHaveLength(0);
    for (const width of [1280, 400])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
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

/* No summary on a running session: the outline stays, with one sentence on what a summary adds, how large the
   read is, Summarize, and what is sent behind its own popover. Nothing is posted until the press. */
export const NoSummary: Story = {
  render: () => <SummaryPage summary={ABSENT} ended={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const none = await stateOf(region, 'none');
    await expect(none).toHaveTextContent(SUMMARY_ADDS);
    await expect(none.querySelector('[data-next-summary-size]')).toHaveTextContent(
      'About 6 entries to read.',
    );
    await expect(region.querySelector('[data-next-outline="blocks"]')).not.toBeNull();
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
    ).toHaveTextContent('A phase title was withheld here.');
    await neverDone(region);
  },
};

/* Interrupted with no saved summary: the reason in the reader's words, the parts it kept, Summarize, and the
   outline below. */
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
    await userEvent.click(
      await within(document.body).findByRole('button', { name: 'Pause model calls' }),
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
   naming the new destination when where summaries go changes. Turn off summaries sits beside it. */
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
    await expect(first).toHaveTextContent('Anthropic');
    await expect(within(first).getByRole('button', { name: 'Turn off summaries' })).toBeVisible();
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
      within(marked).getByRole('button', { name: 'Go to the departure card: Goal' }),
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
      'Open the entry, cited for “You asked for retry with backoff on the webhook handler.”, in Full activity',
    );
    await expect(entryRow(canvasElement, 'p1')).toBeNull();
    await userEvent.click(chip);
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
    await userEvent.click(
      within(summary).getByRole('button', {
        name: /^Open the entry, cited for “You asked about a missing entry\.”/,
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

/* Delete summary removes it and does not summarize the session again on this open. */
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
    await waitFor(() => expect(region.querySelector('[data-next-summary]')).toBeNull());
    await poll();
    await expect(script.posts).toEqual([
      { path: '/api/summary/delete', body: { harness: 'claude', sid: 's1' } },
    ]);
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
          lede: { text: 'The agent worked on the rebase of PR 56.', cites: [SAMPLE_SAID] },
          blocks: [
            block(SAMPLE_PHASE_START, SAMPLE_SAID, 3, [
              {
                title: 'Writing the failing test',
                bullets: [
                  bullet('Said it is writing the failing test first.', 'said', [
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

const SAMPLE_PHASE_START = 'fact:2e1135d2f9e44011';
const SAMPLE_SAID = 'fact:fd062660762701e6';

export const SampleDrawsAStoredSummary: Story = {
  render: () => <SampleWithSummary />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const summary = await summaryOf(region);
    await expect(within(summary).getByRole('heading', { level: 3 })).toHaveTextContent(
      'Writing the failing test',
    );
    await attributed(summary);
    // The sample session has not ended, so its open posts nothing, and the controls are held.
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
    await userEvent.click(chip);
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
    const row = summary.querySelector('[data-next-summary-bullet="asked"]') as HTMLElement;
    await expect(row.querySelector('[data-next-summary-text]')).toHaveTextContent(
      'You said: Confirmed the parser change is in scope.',
    );
    await waitFor(() =>
      expect(
        within(row).getByRole('button', {
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
    const [shownRow, withheldRow] = [
      ...summary.querySelectorAll<HTMLElement>('[data-next-summary-bullet="failed"]'),
    ];
    await expect(shownRow?.querySelector('[data-next-summary-text]')).toHaveTextContent(
      'Failed as the tool reported: Ran pytest tests/test_webhook.py.',
    );
    await waitFor(() =>
      expect(
        within(shownRow as HTMLElement).getByRole('button', {
          name: /cited for “Failed as the tool reported: Ran pytest/,
        }),
      ).toBeVisible(),
    );
    await expect(withheldRow).toHaveTextContent(/^Failed as the tool reported: Withheld:/);
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
    await expect(row.querySelector('[data-next-summary-unlinked]')).toHaveTextContent(
      '1 cited entry Full activity cannot open from here',
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
   press was made, not above the summary. */
export const MissingLineStaysInTheOutline: Story = {
  render: () => {
    const outline = claudeOutline({}, true) as { blocks: Record<string, unknown>[] };
    const [first, ...rest] = outline.blocks;
    return (
      <SummaryPage
        summary={storedSummary()}
        outline={{
          ...outline,
          blocks: [
            {
              ...first,
              prompt: { fact_id: 'p9', title: 'An entry no page holds.', at: 1 },
              span: { first: 'p9', last: 'p9', entries: 1, from_at: 1, to_at: 1 },
            },
            ...rest,
          ],
        }}
      />
    );
  },
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
    await userEvent.click(
      within(outline).getAllByRole('button', { name: /^Open the entry/ })[0] as HTMLElement,
    );
    await waitFor(() =>
      expect(outline.querySelector('[data-next-outline-missing]')).not.toBeNull(),
    );
    await expect(region.querySelectorAll('[data-next-outline-missing]')).toHaveLength(1);
  },
};
