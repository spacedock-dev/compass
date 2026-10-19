import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor } from 'storybook/test';
import '../src/drift/drift.css';
import { FeedbackHint } from '../src/intent/FeedbackHint';
import { DisclosureParts } from '../src/drift/ReadingControl';

/* What the Drift card says after a press that cannot finish, and how the list of what is sent reads. The
   answer to a press is one short line with an info mark, and the rest of the sentence opens from the mark; the
   list of what is sent is a short form with labels in weight, where it was a paragraph that ran the width of
   the card. Both run in real Chromium, because what is asserted is layout and hover. */

const meta = {
  title: 'Drift/Readability',
  component: FeedbackHint,
} satisfies Meta<typeof FeedbackHint>;
export default meta;
type Story = StoryObj<typeof meta>;

const WHOLE =
  'That direction could not be verified as later than your intent in the current record. Nothing was settled and no analysis was started.';

export const PressAnswerIsOneLine: Story = {
  args: { id: 'answer', message: WHOLE },
  render: (args) => (
    <div style={{ width: 240 }}>
      <button type="button">Keep my intent and analyze</button>
      <FeedbackHint {...args} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const trigger = canvasElement.querySelector('[data-next-action-feedback-short]') as HTMLElement;
    await expect(trigger).toHaveTextContent('Direction unverified');
    // One line at the card's narrowest column, where the whole sentence ran to seven.
    await expect(trigger.getBoundingClientRect().height).toBeLessThan(40);
    await expect(document.querySelector('[data-slot="popover-content"][data-open]')).toBeNull();
    await userEvent.hover(trigger);
    await waitFor(() => {
      const popup = [...document.querySelectorAll('[data-slot="popover-content"]')].find(
        (node) => node.textContent === WHOLE && node.hasAttribute('data-open'),
      );
      expect(popup).toBeDefined();
    });
    await userEvent.unhover(trigger);
  },
};

export const SentListReadsAsAShortForm: StoryObj<typeof DisclosureParts> = {
  render: () => (
    <div style={{ width: 360 }}>
      <DisclosureParts
        id="sent"
        parts={[
          "This session's own harness reads it.",
          'Sent: your goal and a bounded set of the session’s entries, with your messages and the agent’s messages up to 1,000 characters each.',
          'Tool output included: a check’s command, result and last 180 characters of output.',
          'To: Anthropic, off this machine, with credential shapes redacted, through your Claude Code CLI.',
        ]}
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const items = [...canvasElement.querySelectorAll('li')];
    await expect(items).toHaveLength(4);
    const labels = [...canvasElement.querySelectorAll('li strong')];
    await expect(labels.map((label) => label.textContent)).toEqual([
      'Sent:',
      'Tool output included:',
      'To:',
    ]);
    for (const label of labels) {
      await expect(Number(getComputedStyle(label).fontWeight)).toBeGreaterThanOrEqual(600);
    }
    // Each item is its own block with room between them, not one run of words.
    const tops = items.map((item) => item.getBoundingClientRect().top);
    await expect(new Set(tops).size).toBe(4);
    const [first, second] = items;
    const gap =
      (second?.getBoundingClientRect().top ?? 0) - (first?.getBoundingClientRect().bottom ?? 0);
    await expect(gap).toBeGreaterThan(2);
  },
};
