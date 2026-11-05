import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import {
  EARLIER_READING,
  LONG_INTERRUPTED_SENTENCE,
  PARTIAL_READING,
  PARTIAL_WHY,
} from '../test/longReading';
import { DriftScenario, failedCheck, fact, readingScenario } from './drift.scenario';

const meta = {
  title: 'Drift/Long partial and interrupted outcomes',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;
const facts = [failedCheck('c1', 500)];
const reading = readingScenario([]);
const session = { annotation_assessment: PARTIAL_READING, annotation_reading_count: 1 };

export const LocalDepartureWithoutGlobalReassurance: Story = {
  args: { scenario: { session, facts, reading } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText('The retry check failed.')).toBeVisible();
    await expect(await within(root).findByText(PARTIAL_WHY)).toBeVisible();
    await expect(root).toHaveTextContent("Can't tell");
    await expect(root.textContent).not.toMatch(/Nothing departs|On track|All.*consistent/);
    await expect(reading.posts).toHaveLength(0);
  },
};

const interrupted = {
  ...session,
  annotation_reading_withheld: LONG_INTERRUPTED_SENTENCE,
  annotation_reading_withheld_at: 1001,
};
export const RestartKeepsTheEarlierReadingVisiblyOlder: Story = {
  args: { scenario: { session: interrupted, facts, reading } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText(EARLIER_READING)).toBeVisible();
    await expect(
      await within(root).findByText(new RegExp('Last analysis.*Compass stopped before')),
    ).toHaveTextContent(LONG_INTERRUPTED_SENTENCE);
    await expect(await within(root).findByText('The retry check failed.')).toBeVisible();
    await expect(root.querySelectorAll('[data-next-long-interrupted]')).toHaveLength(1);
    await expect(reading.posts).toHaveLength(0);
  },
};

export const PendingDirectionAndPauseKeepTheRestartOutcome: Story = {
  args: {
    scenario: {
      session: interrupted,
      facts: [
        ...facts,
        fact('u2', 1050, {
          type: 'user_message',
          by: 'person:me',
          summary: 'Use the new queue instead',
        }),
      ],
      payload: { reading: { off: true, consent: false, reason: 'model-calls-paused' } },
      reading,
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText(EARLIER_READING)).toBeVisible();
    await expect(
      await within(root).findByText(new RegExp('Last analysis.*Compass stopped before')),
    ).toHaveTextContent(LONG_INTERRUPTED_SENTENCE);
    await expect(await within(root).findByRole('button', { name: 'Leave it' })).toBeVisible();
    await expect(root).toHaveTextContent('Model calls are paused');
    await expect(root.querySelectorAll('[data-next-long-interrupted]')).toHaveLength(1);
    await expect(reading.posts).toHaveLength(0);
  },
};
