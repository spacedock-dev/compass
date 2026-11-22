import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useState } from 'react';
import { Disclosure } from '../src/controls/Disclosure';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { testControls } from '../src/controls/testControls';
import { ABSENT, SummaryPage, grant } from './summary.scenario';
import { Button } from '../src/ui/button';
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
    await userEvent.click(canvas.getByText('Show technical details', { exact: true }));
    await waitFor(() => expect(canvas.getByText('16,384 bytes per part.')).toBeVisible());
  },
};
