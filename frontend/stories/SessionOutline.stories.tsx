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

/* Real data: the outline's check ids are not the record's, so a failure has no chip and a part that ends on a
   check is drawn from where it starts. */
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
    // The failure in the failure colour, and no chip: no record page carries the outline's id for it.
    const failure = first.querySelector('[data-next-outline-failure]') as HTMLElement;
    await expect(failure).toHaveTextContent(
      'Failed as the tool reported: pytest tests/test_webhook.py',
    );
    await expect(getComputedStyle(failure).color).toBe('rgb(228, 136, 106)');
    await waitFor(() =>
      expect(first.querySelector('[data-next-outline-span]')).toHaveTextContent('Starts at#1'),
    );
    await expect(within(failure).queryByRole('button')).toBeNull();
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

/* The future case, once the outline's check ids are the record's: the failure and the span's end get chips,
   and the failure's chip opens Full activity on the check. */
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
    await waitFor(() =>
      expect(first.querySelector('[data-next-outline-span]')).toHaveTextContent('Entries#1to#2.2'),
    );
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
    const chip = await within(region).findByRole('link', {
      name: 'Open entry #3, where this part starts, in Full activity',
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
        canvasElement.querySelector('[data-next-cockpit-work] [data-next-entry-id="p2"]'),
      ),
    );
  },
};

const entryRow = (root: HTMLElement, id: string) =>
  root.querySelector(`[data-next-cockpit-work] [data-next-entry-id="${id}"]`);

/* A prompt the page does not hold yet: its chip reads older record pages for it, then lands on it. */
export const ColdPromptChipReadsOlderPages: Story = {
  render: () => <OutlinePage outline={claudeOutline()} paged />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const chip = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-outline-entry="p1"]');
      if (!node) throw new Error('no chip yet');
      return node;
    });
    await expect(chip).toHaveAccessibleName(
      'Open an older entry the page has not read yet, where this part starts, in Full activity',
    );
    // Never the bare word "entry": the chip says why it has no number yet.
    await expect(chip).toHaveTextContent('older entry');
    await expect(entryRow(canvasElement, 'p1')).toBeNull();
    await userEvent.click(chip);
    await waitFor(() => expect(document.activeElement).toBe(entryRow(canvasElement, 'p1')));
    await expect(region.querySelector('[data-next-outline-missing]')).toBeNull();
  },
};

/* A slow press that settles after a later press leaves focus where the later press put it. */
export const LaterPressWins: Story = {
  render: () => <OutlinePage outline={claudeOutline()} paged />,
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    script.holdOlder = true;
    const cold = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-outline-entry="p1"]');
      if (!node) throw new Error('no chip yet');
      return node;
    });
    await userEvent.click(cold);
    await waitFor(() => expect(script.releaseOlder).not.toBeNull());
    const fast = region.querySelector<HTMLElement>('[data-next-outline-entry="p2"]') as HTMLElement;
    await userEvent.click(fast);
    await waitFor(() => expect(document.activeElement).toBe(entryRow(canvasElement, 'p2')));
    script.releaseOlder?.();
    await waitFor(() => expect(entryRow(canvasElement, 'p1')).not.toBeNull());
    // Two frames: the slow press's settle runs in one.
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await expect(document.activeElement).toBe(entryRow(canvasElement, 'p2'));
    await expect(region.querySelector('[data-next-outline-missing]')).toBeNull();
  },
};

/* A prompt no record page holds: the press opens Full activity and says plainly that it does not show it. */
export const EntryNotInFullActivity: Story = {
  render: () => {
    const base = claudeOutline();
    const [first, second] = base.blocks;
    return (
      <OutlinePage
        outline={{
          ...base,
          blocks: [
            {
              ...second,
              prompt: { fact_id: 'p0', title: 'An earlier message.', at: G - 900 },
              span: { first: 'p0', last: 'p0', entries: 1, from_at: G - 900, to_at: G - 900 },
            },
            first,
          ],
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const region = await card(canvasElement);
    const chip = await waitFor(() => {
      const node = region.querySelector<HTMLElement>('[data-next-outline-entry="p0"]');
      if (!node) throw new Error('no chip yet');
      return node;
    });
    await userEvent.click(chip);
    const note = await within(region).findByRole('status');
    await expect(note).toHaveTextContent(
      'Full activity does not show that entry: it could not be loaded, or it sits in a folded run of checks.',
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
      'Before the first message of yours this outline read',
    );
  },
};
