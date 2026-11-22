import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useState } from 'react';
import { Disclosure } from '../src/controls/Disclosure';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { testControls } from '../src/controls/testControls';
import { formatSize } from '../src/shell/format';
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

function SizeExample() {
  const [kit] = useState(() => testControls());
  const bytes = 16_384;
  return (
    <ControlsProvider controls={kit.controls}>
      <Disclosure disclosureKey="story:sent" summary="What is sent">
        <p>{`Up to ${formatSize(bytes, 'en-US')} at a time`}</p>
        <Disclosure disclosureKey="story:sent-detail" summary="Show technical details">
          <p>{`${bytes.toLocaleString('en-US')} bytes`}</p>
        </Disclosure>
      </Disclosure>
    </ControlsProvider>
  );
}

export const WhatIsSentSize: Story = {
  render: () => <SizeExample />,
  args: { variant: 'accordion' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'What is sent' }));
    await waitFor(() => expect(canvas.getByText('Up to 16 KB at a time')).toBeVisible());
    await expect(canvas.getByText('16,384 bytes')).not.toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Show technical details' }));
    await waitFor(() => expect(canvas.getByText('16,384 bytes')).toBeVisible());
  },
};
