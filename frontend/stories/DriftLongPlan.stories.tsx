import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
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
    await expect(root).toHaveTextContent('Source and analysis preparation: 60 seconds maximum.');
    await expect(root).toHaveTextContent('model waits are excluded');
    await expect(root).toHaveTextContent('not a guarantee');
    await expect(root).toHaveTextContent('17 model calls total');
    await expect(root).toHaveTextContent('GitHub checks: enabled');
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
const adoptionPreview = { descriptor: LONG_PLAN, gets: 0 };
const adoptionReading = readingScenario([]);
const adoption = {
  posts: [] as Record<string, unknown>[],
  refreshedPlan: {
    ...LONG_PLAN,
    binding: 'b'.repeat(64),
    intent: { ...LONG_PLAN.intent, revision: 4, start_at: 100 },
  },
};
export const DraftedGoalSavesThenRequiresFreshPreview: Story = {
  args: {
    scenario: {
      longPlan: adoptionPreview,
      reading: adoptionReading,
      goalAdoption: adoption,
      session: {
        annotation_goal: '',
        annotation_goal_source: '',
        first_prompt: 'Ship the queue',
        first_prompt_at: 100,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const root = await canvas.findByRole('region', { name: 'Drift' });
    await userEvent.click(
      await within(root).findByRole('button', { name: 'Long analysis options' }),
    );
    await userEvent.click(await within(root).findByRole('button', { name: 'Start long analysis' }));
    await waitFor(() =>
      expect(root).toHaveTextContent('Your goal was saved. Refresh the long preview'),
    );
    await expect(root).toHaveTextContent('reading window');
    await expect(adoptionReading.posts).toHaveLength(0);
    await expect(adoption.posts).toHaveLength(1);
    await expect(adoption.posts[0]).toMatchObject({
      adopt: 'first-prompt',
      expected_prompt: 'Ship the queue',
      expected_prompt_at: 100,
      expected_revision: 3,
    });
    await expect(adoptionPreview.gets).toBe(1);
    await expect(
      canvasElement.querySelector('textarea[data-next-cockpit-held-kind="goal"]'),
    ).toHaveValue('Ship the queue');
    await userEvent.click(
      await within(root).findByRole('button', { name: 'Refresh long preview' }),
    );
    await waitFor(() => expect(root).toHaveTextContent('Saved intent revision: 4'));
    await expect(adoptionReading.posts).toHaveLength(0);
    await userEvent.click(await within(root).findByRole('button', { name: 'Start long analysis' }));
    await waitFor(() => expect(adoptionReading.posts).toHaveLength(1));
    await expect(adoptionReading.posts[0]).toMatchObject({
      mode: 'long',
      expected_revision: 4,
      plan_binding: adoption.refreshedPlan.binding,
    });
    await expect(adoptionReading.posts[0]).not.toHaveProperty('adopt');
  },
};
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
