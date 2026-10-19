import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { OUTLINE_FAILED, OUTLINE_LABEL, OUTLINE_LOADING } from '../src/sessions/outline';
import {
  G,
  OutlinePage,
  claudeOutline,
  codexOutline,
  script,
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
    const [first, second] = [...blocks] as [HTMLElement, HTMLElement];
    await expect(
      within(first).getByText('Add retry with backoff to the webhook handler.'),
    ).toBeVisible();
    await expect(first.querySelector('[data-next-outline-counts]')).toHaveTextContent(
      '4 entries · 1 agent reply · 2 checks run, 1 failed as the tool reported · 3 files written in src/webhook (2), tests (1)',
    );
    // The failure in the failure colour.
    const failure = first.querySelector('[data-next-outline-failure="c1"]') as HTMLElement;
    await expect(failure).toHaveTextContent(
      'Failed as the tool reported: pytest tests/test_webhook.py',
    );
    await expect(getComputedStyle(failure).color).toBe('rgb(228, 136, 106)');
    // The span as #n chips, numbered as Full activity numbers them.
    await waitFor(() =>
      expect(first.querySelector('[data-next-outline-span]')).toHaveTextContent('Entries#1to#2.2'),
    );
    await expect(second.querySelector('[data-next-outline-span]')).toHaveTextContent(
      'Entries#3to#4',
    );
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

/* A chip opens Full activity and lands on the entry it names. */
export const ChipOpensFullActivity: Story = {
  render: () => <OutlinePage outline={claudeOutline()} />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('button', { name: 'Full activity' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    const chip = await within(region).findByRole('button', {
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
    for (const block of blocks) {
      await expect(block.querySelector('[data-next-outline-counts]')).toHaveTextContent(
        /^1 entry$/,
      );
    }
    await expect(region).not.toHaveTextContent(/checks run|files written|agent repl(y|ies) ·/);
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
            unread: [
              { start_offset: 0, end_offset: 900, reason: 'before_window', stream: 'parent' },
            ],
          },
          blocks: [
            {
              ...first,
              prompt: null,
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
      '2 earlier messages of yours are not shown here. Full activity lists every entry.',
    );
    await expect(region.querySelector('[data-next-outline-prompt="none"]')).toHaveTextContent(
      'Before the first message of yours this outline read',
    );
  },
};
