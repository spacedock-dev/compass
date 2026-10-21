import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import {
  OUTLINE_FAILED,
  OUTLINE_LABEL,
  OUTLINE_LOADING,
  STAMP_FAILED,
} from '../src/sessions/outline';
import {
  G,
  OutlinePage,
  claudeOutline,
  codexOutline,
  script,
  staleOutline,
  unsupportedOutline,
} from './outline.scenario';

/* The What the session has done card before any summary exists: Compass's outline of the session, one block
   per message of the reader's, made with no model call. Every story mounts the real page over a scripted
   backend whose focused context carries `sources.outline`. */

const meta = { title: 'Sessions/What the session has done' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const card = async (root: HTMLElement) =>
  within(root).findByRole('region', { name: 'What the session has done' });

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

/* Real data: the outline's check ids are not the record's, so a failure has no chip. */
export const Outline: Story = {
  render: () => <OutlinePage outline={claudeOutline()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const box = within(region);
    await box.findByText(OUTLINE_LABEL);
    // Labelled as Compass's grouping, never as a summary.
    await expect(region).not.toHaveTextContent(/summary/i);
    const blocks = region.querySelectorAll('[data-next-outline-block]');
    await expect(blocks).toHaveLength(2);
    const [first] = [...blocks] as [HTMLElement];
    await expect(
      within(first).getByText('Add retry with backoff to the webhook handler.'),
    ).toBeVisible();
    // Short sentences: no "4 entries", no "(2)" repeating a count, and the failure is not counted twice.
    await expect(first.querySelector('[data-next-outline-counts]')).toHaveTextContent(
      'The agent replied 1 time, ran 2 checks and wrote 3 files in src/webhook and tests.',
    );
    // The failure in the failure colour, and no chip: no record page carries the outline's id for it.
    const failures = first.querySelectorAll('[data-next-outline-failure]');
    await expect(failures).toHaveLength(1);
    const failure = failures[0] as HTMLElement;
    await expect(failure).toHaveTextContent(
      'Failed as the tool reported: pytest tests/test_webhook.py',
    );
    await expect(getComputedStyle(failure).color).toBe('rgb(228, 136, 106)');
    await expect(within(failure).queryByRole('button')).toBeNull();
    // No entry anchors on a part: not "Starts at #1", not "Entries #3 to #4", and no number the reader has not seen.
    await expect(region.querySelector('[data-next-outline-span]')).toBeNull();
    await expect(box.queryByText(/Starts at|Entries|Ends at/)).toBeNull();
    for (const line of region.querySelectorAll('[data-next-outline-counts]'))
      await expect(line.textContent).not.toMatch(/#\d|\(\d+\)|messages with|entr(y|ies)/);
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^updated \d\d:\d\d · still running$/,
    );
    // The summary's controls region is there for the later part, and empty.
    const controls = region.querySelector('[data-next-session-summary-controls]') as HTMLElement;
    await expect(controls).toBeEmptyDOMElement();
    await expect(controls).not.toBeVisible();
    for (const width of [1280, 400])
      await atWidth(width, async () => {
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
  },
};

/* The future case, once the outline's check ids are the record's: the failure gets a chip, and it opens Full
   activity on the check. A part's own start and end never get one. */
export const MatchedIdsFutureCase: Story = {
  render: () => <OutlinePage outline={claudeOutline({}, true)} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const canvas = within(canvasElement);
    const first = (await waitFor(() => {
      const node = region.querySelector('[data-next-outline-block]');
      if (!node) throw new Error('no block yet');
      return node;
    })) as HTMLElement;
    await expect(first.querySelector('[data-next-outline-span]')).toBeNull();
    const chip = await within(region).findByRole('link', {
      name: 'Open entry #2.1, the failed check, in Full activity',
    });
    await userEvent.click(chip);
    await waitFor(() =>
      expect(canvas.getByRole('button', { name: 'Full activity' })).toHaveAttribute(
        'aria-expanded',
        'true',
      ),
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(
        canvasElement.querySelector('[data-next-cockpit-work] [data-next-entry-id="c1"]'),
      ),
    );
  },
};

/* With annotations off nothing else on the page reads the focused context; the card reads it itself. */
export const AnnotationsOff: Story = {
  render: () => <OutlinePage outline={claudeOutline()} annotate={false} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(OUTLINE_LABEL);
    await expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(2);
  },
};

/* A refresh that fails keeps the outline drawn, and the stamp says the update could not be read rather than
   dating the outline to the failed read. */
export const RefreshFailed: Story = {
  render: () => <OutlinePage outline={claudeOutline()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(OUTLINE_LABEL);
    script.outline = 'error';
    await userEvent.click(
      within(canvasElement).getByRole('button', { name: 'Simulate board poll' }),
    );
    await waitFor(() =>
      expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
        `${STAMP_FAILED} · still running`,
      ),
    );
    await expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(2);
  },
};

export const Loading: Story = {
  render: () => <OutlinePage outline="stall" />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const status = await within(region).findByRole('status');
    await expect(status).toHaveTextContent(OUTLINE_LOADING);
    await expect(region.querySelector('[data-next-outline-stamp]')).toBeNull();
    script.outline = claudeOutline();
    await waitFor(() => expect(script.release).not.toBeNull());
    script.release?.();
    await within(region).findByText(OUTLINE_LABEL);
  },
};

export const ReadFailed: Story = {
  render: () => <OutlinePage outline="error" />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(OUTLINE_FAILED);
  },
};

/* Codex: the reader's own messages as blocks, and a plain statement that it has no agent replies or checks. */
export const Codex: Story = {
  render: () => <OutlinePage harness="codex" outline={codexOutline()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(
      'Only your messages are read for this harness: the outline has no agent replies, checks or files.',
    );
    const blocks = [...region.querySelectorAll<HTMLElement>('[data-next-outline-block]')];
    await expect(blocks).toHaveLength(2);
    // No sentence about work this harness does not read: a zero would stand for "not looked at".
    for (const block of blocks)
      await expect(block.querySelector('[data-next-outline-counts]')).toBeNull();
    await expect(region).not.toHaveTextContent(/ran \d+ checks?|wrote \d+ files?|agent replied/);
  },
};

/* Pi has no paged record, and the card says so in plain words rather than drawing an empty outline. */
export const PiHasNoOutline: Story = {
  render: () => <OutlinePage harness="pi" outline={unsupportedOutline('pi')} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(
      'Pi keeps no record Compass can page through, so this session has no outline. Full activity below lists what the harness reported.',
    );
    await expect(region.querySelector('[data-next-outline-block]')).toBeNull();
    await expect(region.querySelector('[data-next-outline-stamp]')).toBeNull();
  },
};

export const Ended: Story = {
  render: () => <OutlinePage outline={claudeOutline()} ended />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(OUTLINE_LABEL);
    await expect(region.querySelector('[data-next-outline-stamp]')).toHaveTextContent(
      /^updated \d\d:\d\d$/,
    );
  },
};

/* A running session's outline grows with the board: a new message of the reader's becomes a new block on
   the next poll. */
/* A running session's read that overlapped an append answers stale. The last good outline stays drawn rather
   than flickering to the stale sentence until the next revision. */
export const StaleReadKeepsTheLastOutline: Story = {
  render: () => <OutlinePage outline={claudeOutline()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(OUTLINE_LABEL);
    await expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(2);
    const before = script.focused;
    script.outline = staleOutline();
    await userEvent.click(
      within(canvasElement).getByRole('button', { name: 'Simulate board poll' }),
    );
    await waitFor(() => expect(script.focused).toBeGreaterThan(before));
    await new Promise((resolve) => setTimeout(resolve, 50));
    await expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(2);
    await expect(region).not.toHaveTextContent(/changed while Compass was reading/);
    await expect(
      within(region).getByText('Keep the diff small and leave the tests alone.'),
    ).toBeVisible();
  },
};

export const RunningUpdatesWithTheBoard: Story = {
  render: () => {
    const base = claudeOutline();
    return <OutlinePage outline={{ ...base, blocks: base.blocks.slice(0, 1) }} />;
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    await within(region).findByText(OUTLINE_LABEL);
    await expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(1);
    script.outline = claudeOutline();
    await userEvent.click(
      within(canvasElement).getByRole('button', { name: 'Simulate board poll' }),
    );
    await waitFor(() =>
      expect(region.querySelectorAll('[data-next-outline-block]')).toHaveLength(2),
    );
    await expect(
      within(region).getByText('Keep the diff small and leave the tests alone.'),
    ).toBeVisible();
  },
};

/* A read that started partway and work before the first prompt it holds. */
export const StartsPartway: Story = {
  render: () => {
    const base = claudeOutline();
    const [first] = base.blocks;
    return (
      <OutlinePage
        outline={{
          ...base,
          more_blocks: 2,
          coverage: {
            ...base.coverage,
            complete: false,
            starts_at: 'a1',
            start_offset: 900,
            unread: [
              { start_offset: 0, end_offset: 900, reason: 'before_window', stream: 'parent' },
            ],
          },
          blocks: [
            {
              ...first,
              prompt: null,
              opening: false,
              span: { first: 'a1', last: 'c2', entries: 3, from_at: G - 550, to_at: G - 498 },
            },
          ],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const box = within(region);
    await box.findByText(
      "Compass read only the newest part of this session's record, so the outline starts partway.",
    );
    await box.findByText(
      '2 earlier parts of this session are not shown here. Full activity lists every entry.',
    );
    await expect(region.querySelector('[data-next-outline-prompt="none"]')).toHaveTextContent(
      'Work carrying on from earlier in this session',
    );
  },
};

/* The scenario's outline and its two blocks, narrowed once. */
function twoBlocks() {
  const base = claudeOutline();
  const [first, second] = base.blocks;
  if (!first || !second) throw new Error('the scenario outline holds two blocks');
  return { base, first, second };
}

/* A session that passed the read bound: the newest window starts after its first prompt, and the outline still
   opens at that prompt. The part after the gap has no prompt to name, and the note says what lies between. */
export const OpensAtTheFirstPromptBeyondTheWindow: Story = {
  render: () => {
    const { base, first, second } = twoBlocks();
    return (
      <OutlinePage
        outline={{
          ...base,
          more_blocks: 0,
          coverage: {
            ...base.coverage,
            complete: false,
            starts_at: 'a9',
            start_offset: 900000,
            unread: [
              { start_offset: 0, end_offset: 900000, reason: 'before_window', stream: 'parent' },
            ],
          },
          blocks: [
            { ...first, partial: true },
            {
              ...second,
              prompt: null,
              opening: false,
              span: { first: 'a9', last: 'a9', entries: 1, from_at: G - 90, to_at: G - 90 },
              counts: { ...second.counts, agent_messages: 2 },
            },
          ],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const box = within(region);
    await box.findByText(
      'Compass read your first message and the newest part of this session. What happened between them is not outlined here.',
    );
    await expect(box.queryByText(/starts partway/)).toBeNull();
    const [opening, later] = [
      ...region.querySelectorAll<HTMLElement>('[data-next-outline-block]'),
    ] as [HTMLElement, HTMLElement];
    // The first block is the session's first prompt, not "Before the first message of yours this outline read".
    await expect(opening).toHaveAttribute('data-next-outline-opening');
    await expect(
      within(opening).getByText('Add retry with backoff to the webhook handler.'),
    ).toBeVisible();
    // Its counts end where the first read did, and it says so.
    await expect(opening.querySelector('[data-next-outline-counts]')).toHaveTextContent(
      /Counted only as far as Compass read\.$/,
    );
    await expect(later.querySelector('[data-next-outline-prompt="none"]')).toHaveTextContent(
      'Work carrying on from earlier in this session',
    );
    await expect(region).not.toHaveTextContent(
      'Before the first message of yours this outline read',
    );
  },
};

/* A failing run followed by a passing run of the same check is a red test that was fixed: said plainly, not in
   the failure colour, and not listed as a failure. A check still red after its last run is, once. */
export const AFixedRedTestIsNotAFailure: Story = {
  render: () => {
    const { base, first, second } = twoBlocks();
    return (
      <OutlinePage
        outline={{
          ...base,
          blocks: [
            {
              ...first,
              counts: { ...first.counts, checks: 3, checks_failed: 0, checks_fixed: 1 },
              failures: [],
            },
            {
              ...second,
              counts: { ...second.counts, checks: 2, checks_failed: 1, checks_fixed: 0 },
              failures: [{ fact_id: 'fact:lint', title: 'ruff check src', result: 'failed' }],
            },
          ],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const [fixed, red] = [
      ...(await within(region).findAllByRole('listitem')).filter((item) =>
        item.hasAttribute('data-next-outline-block'),
      ),
    ] as [HTMLElement, HTMLElement];
    await expect(fixed.querySelector('[data-next-outline-counts]')).toHaveTextContent(
      'A check that failed passed on a later run.',
    );
    await expect(fixed.querySelector('[data-next-outline-failure]')).toBeNull();
    await expect(fixed).not.toHaveAttribute('data-next-outline-failed');
    await expect(fixed).not.toHaveTextContent(/Failed as the tool reported/);
    // The check that is still failing is listed once, in the failure colour.
    await expect(red.querySelectorAll('[data-next-outline-failure]')).toHaveLength(1);
    await expect(red).toHaveTextContent('Failed as the tool reported: ruff check src');
  },
};

/* The server cuts a prompt's title at its own bound, now back to a word with an ellipsis. The page shows it as
   sent: no partial word, and no second ellipsis. */
export const ServerCutTitleEndsAtAWord: Story = {
  render: () => {
    const { base, first, second } = twoBlocks();
    const title =
      'Implement Linear issue and then check that the launch-grant card no longer says allowed when this dashboard…';
    return (
      <OutlinePage
        outline={{
          ...base,
          blocks: [{ ...first, prompt: { ...first.prompt, title } }, second],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const prompt = (await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-outline-prompt]');
      if (!node) throw new Error('no prompt yet');
      return node;
    })) as HTMLElement;
    const shown = prompt.textContent ?? '';
    await expect(shown).toMatch(/\w…$/);
    await expect(shown).not.toMatch(/……/);
    // Every word shown is a whole word of the sentence the title was cut from.
    const source =
      'Implement Linear issue and then check that the launch-grant card no longer says allowed when this dashboard started after Turning';
    for (const word of shown.slice(0, -1).split(' ')) await expect(source).toContain(word);
  },
};

/* A failure whose fix may lie in the unread gap is said as unread, not listed as still failing. */
export const AnOpeningFailureBeforeTheGapIsUnknown: Story = {
  render: () => {
    const { base, first, second } = twoBlocks();
    return (
      <OutlinePage
        outline={{
          ...base,
          blocks: [
            {
              ...first,
              partial: false,
              counts: { ...first.counts, checks_failed: 0, checks_unknown: 1 },
              failures: [],
            },
            second,
          ],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const [opening] = [
      ...(await within(region).findAllByRole('listitem')).filter((item) =>
        item.hasAttribute('data-next-outline-block'),
      ),
    ] as [HTMLElement];
    await expect(opening.querySelector('[data-next-outline-counts]')).toHaveTextContent(
      'A check failed here; Compass did not read whether a later run fixed it.',
    );
    await expect(opening.querySelector('[data-next-outline-failure]')).toBeNull();
    await expect(opening).not.toHaveTextContent(/still failing/);
  },
};

/* A long first prompt is cut at a word with an ellipsis, never inside one. */
export const LongPromptCutAtAWord: Story = {
  render: () => {
    const { base, first, second } = twoBlocks();
    const title =
      'Implement the launch grant card. The launch-grant card still says "allowed when this dashboard started" after Turning off the grant from the toolbar, and the same stale line stays on the next card as well.';
    return (
      <OutlinePage
        outline={{
          ...base,
          blocks: [{ ...first, prompt: { ...first.prompt, title } }, second],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const prompt = (await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-outline-prompt]');
      if (!node) throw new Error('no prompt yet');
      return node;
    })) as HTMLElement;
    const shown = prompt.textContent ?? '';
    await expect(shown.endsWith('…')).toBe(true);
    await expect(shown).toMatch(/\w…$/);
    const whole = prompt.getAttribute('title') ?? '';
    await expect(whole.startsWith(shown.slice(0, -1))).toBe(true);
    await expect(whole.charAt(shown.length - 1)).toMatch(/^\s?$/);
  },
};
