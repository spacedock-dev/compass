import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { LONG_PLAN } from '../test/longPlan';
import { DriftScenario, readingScenario } from './drift.scenario';

const meta = { title: 'Drift/Long analysis preview', component: DriftScenario } satisfies Meta<
  typeof DriftScenario
>;
export default meta;
type Story = StoryObj<typeof meta>;
const preview = { descriptor: LONG_PLAN, gets: 0 };
const reading = readingScenario([]);
export const ExplicitPreviewThenOneStart: Story = {
  args: { scenario: { longPlan: preview, reading } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    const options = await within(root).findByRole('button', { name: 'Long analysis options' });
    await expect(preview.gets).toBe(0);
    await expect(reading.posts).toHaveLength(0);
    options.focus();
    await userEvent.keyboard('{Enter}');
    const start = await within(root).findByRole('button', { name: 'Start long analysis' });
    await expect(preview.gets).toBe(1);
    await expect(reading.posts).toHaveLength(0);
    await expect(root).toHaveTextContent('not process RSS');
    await expect(root).toHaveTextContent('not a guarantee');
    start.focus();
    await userEvent.keyboard('{Enter}');
    await expect(reading.posts).toHaveLength(1);
    await expect(reading.posts[0]).toMatchObject({ mode: 'long', plan_binding: LONG_PLAN.binding });
    await expect(start).toHaveAttribute('aria-disabled', 'true');
    await userEvent.keyboard('{Enter}');
    await expect(reading.posts).toHaveLength(1);
    await expect(preview.gets).toBe(1);
  },
};
const unavailable = {
  descriptor: {
    ...LONG_PLAN,
    can_start: false,
    reason: 'allowance-unavailable',
    allowance: { ...LONG_PLAN.allowance, state: 'paused' },
  },
  gets: 0,
};
const idle = readingScenario([]);
export const UnavailablePreviewDoesNotStart: Story = {
  args: { scenario: { longPlan: unavailable, reading: idle } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await userEvent.click(
      await within(root).findByRole('button', { name: 'Long analysis options' }),
    );
    const start = await within(root).findByRole('button', { name: 'Start long analysis' });
    await expect(start).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(start);
    await expect(idle.posts).toHaveLength(0);
    const refresh = await within(root).findByRole('button', { name: 'Refresh long preview' });
    refresh.focus();
    await expect(refresh).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    await expect(unavailable.gets).toBe(2);
    await expect(idle.posts).toHaveLength(0);
  },
};
