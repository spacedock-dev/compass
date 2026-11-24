import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useState } from 'react';
import { Disclosure } from '../src/controls/Disclosure';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { testControls } from '../src/controls/testControls';
import { ABSENT, SummaryPage, grant } from './summary.scenario';
import { Button } from '../src/ui/button';
import { atWidth, expectSpansPanel } from './disclosure.flow';
const meta = { title: 'Controls/Disclosure', component: Example } satisfies Meta<typeof Example>;
export default meta;
type Story = StoryObj<typeof meta>;
function Example({ variant }: { variant: 'accordion' | 'popover' }) {
  const [kit] = useState(() => testControls());
  return (
    <ControlsProvider controls={kit.controls}>
      <div id="gallery">
        <Disclosure disclosureKey="story:plan" summary="Project plan" variant={variant}>
          <p>Plan body</p>
          <Button>Inside the plan</Button>
        </Disclosure>
      </div>
    </ControlsProvider>
  );
}
export const Accordion: Story = {
  args: { variant: 'accordion' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole('button', { name: 'Project plan' });
    trigger.focus();
    await userEvent.keyboard('{Enter}');
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(canvas.getByText('Plan body')).toBeVisible());
    await userEvent.keyboard('{Escape}');
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await userEvent.keyboard(' ');
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger).toHaveFocus();
  },
};
export const Popover: Story = {
  args: { variant: 'popover' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole('button', { name: 'Project plan' });
    trigger.focus();
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(canvas.getByRole('dialog', { name: 'Project plan' })).toBeVisible());
    await userEvent.tab();
    await expect(canvas.getByRole('button', { name: 'Inside the plan' })).toHaveFocus();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
    await expect(trigger).toHaveFocus();
    await userEvent.keyboard(' ');
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await userEvent.keyboard(' ');
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger).toHaveFocus();
  },
};

export const WhatIsSentSize: Story = {
  render: () => (
    <SummaryPage
      ended={false}
      grant={grant({ disclosure: 'Sends redacted session text through Claude Code to Anthropic.' })}
      summary={{
        ...ABSENT,
        plan: {
          complete: true,
          parts: 4,
          windows: 3,
          calls: 8,
          minutes: 10,
          largest_read: { windows: 32, window_bytes: 16384, calls: 37, seconds: 600 },
        },
      }}
    />
  ),
  args: { variant: 'accordion' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole('button', { name: 'What is sent to Claude Code' }),
    );
    await waitFor(() => expect(canvas.getByText('Up to 16 KB per part.')).toBeVisible());
    await expect(canvas.queryByText('16,384 bytes per part.')).not.toBeVisible();
    await userEvent.click(await canvas.findByText('Exact byte limits', { exact: true }));
    await waitFor(() => expect(canvas.getByText('16,384 bytes per part.')).toBeVisible());
  },
};

/* Owner, 2026-11-24: an opened panel's sentences span the card on a wide screen. They used to stop at the page's
   540px reading cap, leaving the right half of the card empty. */
export const PanelTextSpansTheCard: Story = {
  render: () => (
    <SummaryPage
      ended={false}
      grant={grant({
        disclosure:
          'Sends to Anthropic through your Claude Code, at most 16 KB at a time: your messages, text relayed in your turn, the agent replies, test and build names with their result, and the paths of files written. Titles of earlier parts go along as context. Everything is redacted first.',
      })}
      summary={ABSENT}
    />
  ),
  args: { variant: 'accordion' },
  play: async ({ canvasElement }) => {
    const restore = await atWidth(1280);
    try {
      const canvas = within(canvasElement);
      const trigger = await canvas.findByRole('button', { name: 'What is sent to Claude Code' });
      await userEvent.click(trigger);
      const panel = document.getElementById(trigger.getAttribute('aria-controls') ?? '');
      if (!panel) throw new Error('The expanded button has no panel');
      const text = await within(panel).findByText(/Everything is redacted first/);
      await waitFor(() => expect(panel.getBoundingClientRect().width).toBeGreaterThan(540));
      await expectSpansPanel(text, panel);
    } finally {
      await restore();
    }
  },
};
