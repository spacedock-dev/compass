import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import {
  FAILED_EVIDENCE_DIAGNOSTIC,
  RESOURCE_LIMIT_DIAGNOSTIC,
  SOURCE_GAP_DIAGNOSTIC,
} from '../test/longCoverage';
import { LONG_DIAGNOSTIC } from '../test/longDiagnostic';
import { LONG_JOB } from '../test/longProgress';
import { PARTIAL_READING, PARTIAL_WHY } from '../test/longReading';
import { DriftScenario, failedCheck, readingScenario } from './drift.scenario';
import { openSessionTechnicalTab } from './sessionTechnical';

const meta = { title: 'Drift/Long coverage and limits', component: DriftScenario } satisfies Meta<
  typeof DriftScenario
>;
export default meta;
type Story = StoryObj<typeof meta>;
const reading = readingScenario([]);
const facts = [failedCheck('c1', 500)];
const session = (diagnostic: unknown) => ({
  annotation_assessment: { ...PARTIAL_READING, read_at: 1100 },
  annotation_long_diagnostic: diagnostic,
});

export const FailedEvidenceRangesKeepQualifiedFindings: Story = {
  args: { scenario: { session: session(FAILED_EVIDENCE_DIAGNOSTIC), facts, reading } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Is it on track?' });
    await expect(within(root).queryByText(/Evidence ranges:/)).toBeNull();
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    const panel = within(canvasElement).getByRole('tabpanel', { name: 'Evidence' });
    await expect(evidence.getByText('An evidence pass failed.')).toBeVisible();
    await expect(
      evidence.getByText(/Evidence ranges: 6 planned; 4 usable; 2 failed; 1 unassigned\./),
    ).toBeVisible();
    await expect(await evidence.findByText('The retry check failed.')).toBeVisible();
    await expect(await evidence.findByText(PARTIAL_WHY)).toBeVisible();
    await expect(
      evidence.getByText('These counts do not establish that all saved work was assessed.'),
    ).toBeVisible();
    await expect(panel.textContent).not.toMatch(/100%|complete coverage/);
    await expect(reading.posts).toHaveLength(0);
  },
};

export const SourceGapAndUnknownExtent: Story = {
  args: { scenario: { session: session(SOURCE_GAP_DIAGNOSTIC), facts, reading } },
  play: async ({ canvasElement }) => {
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(
      evidence.getByText('Source gaps prevented the analysis from covering its saved work.'),
    ).toBeVisible();
    await expect(evidence.getByText(/Source files verified: 1 of 2\./)).toBeVisible();
    await expect(evidence.getByText(/Frozen source extent: 8,192 bytes\./)).toBeVisible();
    await expect(
      evidence.getByText(/Source gap records: 1; additional records omitted: 0\./),
    ).toBeVisible();
    await expect(evidence.getByText(/Unexpanded source extent is unknown\./)).toBeVisible();
    await expect(evidence.getByText('Evidence range measurements are unknown.')).toBeVisible();
    await expect(reading.posts).toHaveLength(0);
  },
};

export const RecordedResourceStopAndPlanCeilings: Story = {
  args: { scenario: { session: session(RESOURCE_LIMIT_DIAGNOSTIC), facts, reading } },
  play: async ({ canvasElement }) => {
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(evidence.getByText('A resource limit stopped the analysis.')).toBeVisible();
    await expect(
      evidence.getByText(/Native source reads: 268,435,456 \/ 268,435,456 bytes/),
    ).toBeVisible();
    await expect(evidence.getByText(/Preparation measured: 60,000 \/ 60,000 ms/)).toHaveTextContent(
      'model waits excluded',
    );
    await expect(evidence.getByText(/not process RSS/)).toBeVisible();
    await expect(reading.posts).toHaveLength(0);
  },
};

export const UnknownSavedCoverageWhileNewJobRuns: Story = {
  args: {
    scenario: {
      session: session(LONG_DIAGNOSTIC),
      facts,
      reading,
      payload: {
        reading_jobs: {
          'claude:s1': { ...LONG_JOB, started_at: 2000, blocked_reason: 'cleanup-unresolved' },
        },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Is it on track?' });
    await expect(
      await within(root).findByText(/Compass could not confirm that the analysis process ended/),
    ).toBeVisible();
    await expect(root.textContent).not.toContain('Current long analysis is still running');
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(evidence.getByText(/Last saved long outcome:/)).toBeVisible();
    await expect(
      evidence.getByText('Current long analysis is unfinished; these are saved measurements.'),
    ).toBeVisible();
    const panel = within(canvasElement).getByRole('tabpanel', { name: 'Evidence' });
    const saved = panel.querySelector('[data-next-long-coverage]');
    await expect(saved).toHaveTextContent('Stop or limit reason: unknown.');
    await expect(saved).toHaveTextContent('Source coverage measurements are unknown.');
    await expect(saved).toHaveTextContent('Evidence range measurements are unknown.');
    await expect(saved).toHaveTextContent('Preparation measured: unknown / 60,000 ms');
    await expect(saved?.textContent).not.toMatch(/0 of 0|0 failed/);
    await expect(reading.posts).toHaveLength(0);
  },
};
