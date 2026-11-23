import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { LONG_DIAGNOSTIC, LONG_INCOMPLETE_SENTENCE, LATEST_OLDER } from '../test/longDiagnostic';
import { PARTIAL_READING, PARTIAL_WHY } from '../test/longReading';
import { DriftScenario, failedCheck, fact, readingScenario } from './drift.scenario';
import { openSessionTechnicalTab } from './sessionTechnical';

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
    const canvas = within(canvasElement);
    const progress = within(await canvas.findByRole('region', { name: 'Is it on track?' }));
    await expect(
      await progress.findByText(LONG_INCOMPLETE_SENTENCE, { exact: false }),
    ).toBeVisible();
    await expect(progress.queryByText(/Calls reserved:/)).toBeNull();
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(await evidence.findByText(LATEST_OLDER)).toBeVisible();
    await expect(evidence.getByText(/Long analysis did not produce a new result\./)).toBeVisible();
    await expect(evidence.getByText(/Calls reserved: at least 4\./)).toBeVisible();
    await expect(await evidence.findByText('The retry check failed.')).toBeVisible();
    await expect(await evidence.findByText(PARTIAL_WHY)).toBeVisible();
    await expect(evidence.getAllByText(/Last saved long outcome:/)).toHaveLength(1);
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
    const root = await within(canvasElement).findByRole('region', { name: 'Is it on track?' });
    const progress = within(root);
    await expect(await progress.findByRole('button', { name: 'Leave it' })).toBeVisible();
    await expect(root).toHaveTextContent('Model calls are paused');
    await expect(
      await progress.findByText(LONG_INCOMPLETE_SENTENCE, { exact: false }),
    ).toBeVisible();
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(await evidence.findByText(LATEST_OLDER)).toBeVisible();
    await expect(evidence.getByText(/Long analysis did not produce a new result\./)).toBeVisible();
    await expect(evidence.getByText(/Calls reserved: at least 4\./)).toBeVisible();
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
    const canvas = within(canvasElement);
    const progress = within(await canvas.findByRole('region', { name: 'Is it on track?' }));
    await expect(await progress.findByText(/Compass found 1 departure/)).toBeVisible();
    await expect(progress.queryByText("Can't tell", { exact: true })).toBeNull();
    await expect(progress.queryByText('On track', { exact: true })).toBeNull();
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(evidence.getByText(/Long analysis saved a partial result\./)).toBeVisible();
    await expect(evidence.getByText('Reserved call accounting is unknown.')).toBeVisible();
    await expect(await evidence.findByText('The retry check failed.')).toBeVisible();
    await expect(await evidence.findByText(PARTIAL_WHY)).toBeVisible();
    await expect(evidence.queryByText(LATEST_OLDER)).toBeNull();
    await expect(reading.posts).toHaveLength(0);
  },
};
