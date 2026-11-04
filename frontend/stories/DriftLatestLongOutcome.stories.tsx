import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { LONG_DIAGNOSTIC, LONG_INCOMPLETE_SENTENCE, LATEST_OLDER } from '../test/longDiagnostic';
import { PARTIAL_READING, PARTIAL_WHY } from '../test/longReading';
import { DriftScenario, failedCheck, fact, readingScenario } from './drift.scenario';

const meta = { title: 'Drift/Latest long outcome', component: DriftScenario } satisfies Meta<
  typeof DriftScenario
>;
export default meta;
type Story = StoryObj<typeof meta>;
const reading = readingScenario([]);
const facts = [failedCheck('c1', 500)];
const session = {
  annotation_assessment: PARTIAL_READING,
  annotation_long_diagnostic: LONG_DIAGNOSTIC,
  annotation_reading_withheld: LONG_INCOMPLETE_SENTENCE,
  annotation_reading_withheld_at: 1100,
};

export const WithheldKeepsTheEarlierReadingAndAccounting: Story = {
  args: { scenario: { session, facts, reading } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText(LATEST_OLDER)).toBeVisible();
    await expect(root.querySelector('[data-next-long-outcome]')).toHaveTextContent(
      'Long analysis did not produce a new result.',
    );
    await expect(root.querySelector('.next-cockpit-reading-outcome')).toHaveTextContent(
      LONG_INCOMPLETE_SENTENCE,
    );
    await expect(root.querySelector('[data-next-long-outcome]')).toHaveTextContent(
      'Calls reserved: at least 4.',
    );
    await expect(await within(root).findByText('The retry check failed.')).toBeVisible();
    await expect(await within(root).findByText(PARTIAL_WHY)).toBeVisible();
    await expect(root.querySelectorAll('[data-next-long-outcome]')).toHaveLength(1);
    await expect(reading.posts).toHaveLength(0);
  },
};
export const PendingDirectionAndPauseKeepLatestOutcome: Story = {
  args: {
    scenario: {
      session,
      facts: [
        ...facts,
        fact('u2', 1050, {
          type: 'user_message',
          by: 'person:me',
          summary: 'Use a different queue',
        }),
      ],
      payload: { reading: { off: true, consent: false, reason: 'model-calls-paused' } },
      reading,
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText(LATEST_OLDER)).toBeVisible();
    await expect(root.querySelector('[data-next-long-outcome]')).toHaveTextContent(
      'Long analysis did not produce a new result.',
    );
    await expect(root.querySelector('.next-cockpit-reading-outcome')).toHaveTextContent(
      LONG_INCOMPLETE_SENTENCE,
    );
    await expect(root).toHaveTextContent('Calls reserved: at least 4.');
    await expect(await within(root).findByRole('button', { name: 'Leave it' })).toBeVisible();
    await expect(root).toHaveTextContent('Model calls are paused');
    await expect(reading.posts).toHaveLength(0);
  },
};
export const PartialFindingsLeaveUnknownsExplicit: Story = {
  args: {
    scenario: {
      facts,
      reading,
      session: {
        annotation_assessment: { ...PARTIAL_READING, read_at: 1100 },
        annotation_long_diagnostic: {
          ...LONG_DIAGNOSTIC,
          outcome: 'partial',
          accounting: { state: 'unknown', totals: null, attempted_job: null },
        },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(root.querySelector('[data-next-long-outcome]')).toHaveTextContent(
      'Long analysis saved a partial result.',
    );
    await expect(root).toHaveTextContent('Reserved call accounting is unknown.');
    await expect(await within(root).findByText('The retry check failed.')).toBeVisible();
    await expect(await within(root).findByText(PARTIAL_WHY)).toBeVisible();
    await expect(root).toHaveTextContent("Can't tell");
    await expect(root.querySelector('[data-next-long-older]')).toBeNull();
    await expect(reading.posts).toHaveLength(0);
  },
};
