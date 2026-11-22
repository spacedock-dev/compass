import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Badge } from '../src/ui/badge';
const meta = { title: 'UI/Badge', component: Badge } satisfies Meta<typeof Badge>;
export default meta;
type Story = StoryObj<typeof meta>;
const smallBadge: NonNullable<Story['play']> = async ({ canvasElement, args }) => {
  const badge = within(canvasElement).getByText(String(args.children));
  await expect(badge).toBeVisible();
  await expect(badge).toHaveAttribute('data-variant', args.variant ?? 'status');
  const css = getComputedStyle(badge);
  await expect(css.fontSize).toBe('13px');
  await expect(css.fontFamily).toContain('Inter');
  await expect(css.textTransform).toBe('none');
};
export const Status: Story = {
  args: { children: 'Waiting on you' },
  play: smallBadge,
};
export const Progress: Story = {
  args: { variant: 'progress', tone: 'high', children: 'Off course' },
  play: smallBadge,
};
export const CountChip: Story = {
  args: { variant: 'count-chip', children: '3' },
  play: smallBadge,
};
export const DriftPill: Story = {
  args: { variant: 'drift-pill', children: 'Badge drift-pill' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CourseTag: Story = {
  args: { variant: 'course-tag', children: 'Badge course-tag' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const NotifyBlocked: Story = {
  args: { variant: 'notify-blocked', children: 'Badge notify-blocked' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const TerminalTag: Story = {
  args: { variant: 'terminal-tag', children: 'Badge terminal-tag' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const WorkFlag: Story = {
  args: { variant: 'work-flag', children: 'Badge work-flag' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
