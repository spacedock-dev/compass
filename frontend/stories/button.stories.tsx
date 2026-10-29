import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useState } from 'react';
import { Button } from '../src/ui/button';
const meta = { title: 'UI/Button', component: Button } satisfies Meta<typeof Button>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {
  args: { variant: 'default', children: 'Button default' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Retry: Story = {
  args: { variant: 'retry', children: 'Button retry' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Answer: Story = {
  args: { variant: 'answer', children: 'Button answer' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Primary: Story = {
  args: { variant: 'primary', children: 'Button primary' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Quiet: Story = {
  args: { variant: 'quiet', children: 'Button quiet' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Bare: Story = {
  args: { variant: 'bare', children: 'Button bare' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Window: Story = {
  args: { variant: 'window', children: 'Button window' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Menu: Story = {
  args: { variant: 'menu', children: 'Button menu' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const ContextAdd: Story = {
  args: { variant: 'context-add', children: 'Button context-add' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Native: Story = {
  args: { variant: 'native', children: 'Button native' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const FilterChip: Story = {
  args: {
    variant: 'filter-chip',
    'aria-label': 'Remove Project: compass',
    children: 'Project: compass',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: 'Remove Project: compass' });
    await expect(node).toBeVisible();
    await expect(node).toHaveTextContent('Project: compass');
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Copy: Story = {
  args: { variant: 'copy', children: 'Button copy' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Raise: Story = {
  args: { variant: 'raise', children: 'Button raise' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const RaisePrimary: Story = {
  args: { variant: 'raise-primary', children: 'Button raise-primary' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Terminal: Story = {
  args: { variant: 'terminal', children: 'Button terminal' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Disabled: Story = {
  args: { disabled: true, children: 'Unavailable action' },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'Unavailable action' }),
    ).toBeDisabled();
  },
};
export const Long: Story = {
  args: { children: 'Save the long intent that explains every expected outcome to the reader' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button')).toBeVisible();
  },
};
export const Pending: Story = {
  render: () => <PendingExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole('button', { name: 'Save' });
    const width = button.getBoundingClientRect().width;
    await userEvent.click(button);
    await expect(button).toHaveAccessibleName('Saving…');
    await expect(button).toHaveAttribute('aria-busy', 'true');
    await expect(button).toHaveAttribute('aria-disabled', 'true');
    await expect(button).toHaveFocus();
    await expect(button.getBoundingClientRect().width).toBe(width);
    await userEvent.keyboard('{Enter} ');
    await userEvent.click(button);
    await expect(canvas.getByRole('status')).toHaveTextContent('1 request');
  },
};
function PendingExample() {
  const [requests, setRequests] = useState(0);
  return (
    <>
      <Button
        reserve="Saving the intent…"
        busyLabel="Saving…"
        aria-busy={requests > 0}
        onClick={() => setRequests(requests + 1)}
      >
        Save
      </Button>
      <output role="status">{requests} request</output>
    </>
  );
}
export const CopyCopied: Story = {
  args: { variant: 'copy', 'data-copy-state': 'copied', children: 'copied' } as NonNullable<
    Story['args']
  >,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'copied' })).toBeVisible();
  },
};
export const CopyFailed: Story = {
  args: { variant: 'copy', 'data-copy-state': 'failed', children: 'failed' } as NonNullable<
    Story['args']
  >,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'failed' })).toBeVisible();
  },
};
export const RaiseSending: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="sending" aria-busy={true}>
      RAISE sending
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RAISE sending' }),
    ).toBeVisible();
  },
};
export const RaiseSent: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="sent" aria-busy={false}>
      RAISE sent
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'RAISE sent' })).toBeVisible();
  },
};
export const RaiseDeclined: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="declined" aria-busy={false}>
      RAISE declined
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RAISE declined' }),
    ).toBeVisible();
  },
};
export const RaiseFailed: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="failed" aria-busy={false}>
      RAISE failed
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'RAISE failed' })).toBeVisible();
  },
};
export const RaiseThrottled: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="throttled" aria-busy={false}>
      RAISE throttled
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RAISE throttled' }),
    ).toBeVisible();
  },
};
export const RaiseStale: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="stale" aria-busy={false}>
      RAISE stale
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'RAISE stale' })).toBeVisible();
  },
};
export const Muted: Story = {
  args: { tone: 'muted', children: 'Muted' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'Muted' })).toBeVisible();
  },
};
export const Consent: Story = {
  args: { size: 'consent', children: 'Consent' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'Consent' })).toBeVisible();
  },
};
export const AccentBorder: Story = {
  args: { accentBorder: true, children: 'AccentBorder' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'AccentBorder' })).toBeVisible();
  },
};
export const StrongBorder: Story = {
  args: { strongBorder: true, children: 'StrongBorder' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'StrongBorder' })).toBeVisible();
  },
};
export const RetryUnavailable: Story = {
  args: { variant: 'retry', 'aria-disabled': true, children: 'RetryUnavailable' },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RetryUnavailable' }),
    ).toBeVisible();
  },
};
