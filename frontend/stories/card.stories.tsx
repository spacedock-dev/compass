import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Card } from '../src/ui/card';
const meta = { title: 'UI/Card', component: Card } satisfies Meta<typeof Card>;
export default meta;
type Story = StoryObj<typeof meta>;
export const SessionRow: Story = {
  args: { variant: 'session-row', children: 'Card session-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SessionCurrent: Story = {
  args: { variant: 'session-current', children: 'Card session-current' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SessionAsk: Story = {
  args: { variant: 'session-ask', children: 'Card session-ask' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SessionLanded: Story = {
  args: { variant: 'session-landed', children: 'Card session-landed' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const IntentRow: Story = {
  args: { variant: 'intent-row', children: 'Card intent-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const IntentPanel: Story = {
  args: { variant: 'intent-panel', children: 'Card intent-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const DriftPanel: Story = {
  args: { variant: 'drift-panel', children: 'Card drift-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ReadingJob: Story = {
  args: { variant: 'reading-job', children: 'Card reading-job' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ReadingNotice: Story = {
  args: { variant: 'reading-notice', children: 'Card reading-notice' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ReadingStale: Story = {
  args: { variant: 'reading-stale', children: 'Card reading-stale' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SteerBox: Story = {
  args: { variant: 'steer-box', children: 'Card steer-box' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const SteerReceipt: Story = {
  args: { variant: 'steer-receipt', children: 'Card steer-receipt' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ProjectRow: Story = {
  args: { variant: 'project-row', children: 'Card project-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ProjectGoal: Story = {
  args: { variant: 'project-goal', children: 'Card project-goal' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ProjectRecovery: Story = {
  args: { variant: 'project-recovery', children: 'Card project-recovery' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CourseRow: Story = {
  args: { variant: 'course-row', children: 'Card course-row' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const StageRule: Story = {
  args: { variant: 'stage-rule', children: 'Card stage-rule' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const RailPanel: Story = {
  args: { variant: 'rail-panel', children: 'Card rail-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const RailWait: Story = {
  args: { variant: 'rail-wait', children: 'Card rail-wait' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const TimelineDetails: Story = {
  args: { variant: 'timeline-details', children: 'Card timeline-details' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const TerminalFrame: Story = {
  args: { variant: 'terminal-frame', children: 'Card terminal-frame' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const AttentionBrief: Story = {
  args: { variant: 'attention-brief', children: 'Card attention-brief' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const AttentionItem: Story = {
  args: { variant: 'attention-item', children: 'Card attention-item' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CapacityBand: Story = {
  args: { variant: 'capacity-band', children: 'Card capacity-band' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const CapacityProspect: Story = {
  args: { variant: 'capacity-prospect', children: 'Card capacity-prospect' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const QuotaConsent: Story = {
  args: { variant: 'quota-consent', children: 'Card quota-consent' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ObserverControls: Story = {
  args: { variant: 'observer-controls', children: 'Card observer-controls' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const WorkPanel: Story = {
  args: { variant: 'work-panel', children: 'Card work-panel' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(args.children as string)).toBeVisible();
  },
};
export const ToneUnknown: Story = {
  args: {
    tone: 'unknown',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
export const ToneWant: Story = {
  args: {
    tone: 'want',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
export const ToneBad: Story = {
  args: {
    tone: 'bad',
    as: 'article',
    'aria-label': 'Current session',
    children: 'Current session',
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
export const ToneOk: Story = {
  args: { tone: 'ok', as: 'article', 'aria-label': 'Current session', children: 'Current session' },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('article', { name: 'Current session' }),
    ).toBeVisible();
  },
};
