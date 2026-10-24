import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Badge } from '../src/ui/badge';
const meta = { title: 'UI/Badge', component: Badge } satisfies Meta<typeof Badge>;
export default meta;
type Story = StoryObj<typeof meta>;
export const SessionState: Story = {
  args: { variant: 'session-state', children: 'Badge session-state' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
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
