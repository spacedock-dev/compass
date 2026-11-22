import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Alert } from '../src/ui/alert';
import { auditContrast, rgbOf } from './a11y.audit';
const meta = { title: 'UI/Alert', component: Alert } satisfies Meta<typeof Alert>;
export default meta;
type Story = StoryObj<typeof meta>;

function stripeFree(
  variant: 'notice' | 'warning' | 'danger',
  message: string,
  tint: number[],
): Story {
  return {
    args: { variant, children: message },
    play: async ({ canvasElement }) => {
      const alert = within(canvasElement).getByRole('status');
      await expect(alert).toHaveTextContent(message);
      await expect(alert).toHaveStyle({ borderWidth: '1px' });
      await expect(rgbOf(getComputedStyle(alert).backgroundColor)).toEqual(tint);
      const reading = auditContrast(canvasElement).measured.find((entry) => entry.text === message);
      await expect(reading?.ratio).toBeGreaterThanOrEqual(4.5);
    },
  };
}

export const Notice = stripeFree(
  'notice',
  'New to Compass? See a sample session.',
  [230, 242, 236],
);
export const Warning = stripeFree(
  'warning',
  'Waiting on you. The session needs a reply.',
  [254, 243, 226],
);
export const Danger = stripeFree('danger', 'Could not load the session.', [247, 239, 236]);
export const SessionHealth: Story = {
  args: { variant: 'session-health', children: 'Alert session-health' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const ObserverStatus: Story = {
  args: { variant: 'observer-status', children: 'Alert observer-status' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const AnswerFailure: Story = {
  args: { variant: 'answer-failure', children: 'Alert answer-failure' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const IntentNote: Story = {
  args: { variant: 'intent-note', children: 'Alert intent-note' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const ShellNotice: Story = {
  args: { variant: 'shell-notice', children: 'Alert shell-notice' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const TerminalAbsence: Story = {
  args: { variant: 'terminal-absence', children: 'Alert terminal-absence' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const TimelineStale: Story = {
  args: { variant: 'timeline-stale', children: 'Alert timeline-stale' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const DriftNudge: Story = {
  args: { variant: 'drift-nudge', children: 'Alert drift-nudge' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('status')).toHaveTextContent(args.children as string);
  },
};
export const ReadingCap: Story = {
  args: { variant: 'reading-cap', children: 'Alert reading-cap' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const alert = canvas.getByRole('status');
    await expect(alert).toHaveTextContent(args.children as string);
    await expect(getComputedStyle(alert).position).toBe('sticky');
  },
};
export const Silent: Story = {
  args: { announce: false, children: 'Quiet notice' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole('status')).toBeNull();
    await expect(canvas.getByText('Quiet notice')).toBeVisible();
  },
};
