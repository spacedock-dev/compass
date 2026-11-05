import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { EVIDENCE_PROGRESS, LONG_JOB } from '../test/longProgress';
import { DriftScenario, readingScenario } from './drift.scenario';

const meta = { title: 'Drift/Long analysis progress', component: DriftScenario } satisfies Meta<
  typeof DriftScenario
>;
export default meta;
type Story = StoryObj<typeof meta>;
const idle = readingScenario([]);
export const UnknownUntilMeasured: Story = {
  args: { scenario: { payload: { reading_jobs: { 'claude:s1': LONG_JOB } }, reading: idle } },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText('Collecting source')).toBeVisible();
    await expect(root).toHaveTextContent('Source files verified: unknown.');
    await expect(root).toHaveTextContent('Evidence pass count: unknown.');
    await expect(root).toHaveTextContent('Reserved call accounting is unknown.');
    await expect(root.textContent).not.toMatch(/0 of 0|%/);
    await expect(await within(root).findByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(idle.posts).toHaveLength(0);
  },
};

const active = readingScenario([]);
export const FourthOfSevenWithActualReservations: Story = {
  args: {
    scenario: {
      payload: {
        reading_jobs: { 'claude:s1': { ...LONG_JOB, phase: 'read', progress: EVIDENCE_PROGRESS } },
      },
      reading: active,
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText('Evidence pass 4 of 7')).toBeVisible();
    await expect(root).toHaveTextContent('Evidence passes finished: 3 of 7.');
    await expect(root).toHaveTextContent('Calls reserved: 4.');
    await expect(root).toHaveTextContent('Assembled input reserved: 24,000 bytes.');
    await expect(root).toHaveTextContent('Reply space reserved: 32,768 bytes.');
    await expect(active.posts).toHaveLength(0);
    const cancel = await within(root).findByRole('button', { name: 'Cancel' });
    cancel.focus();
    await expect(cancel).toHaveFocus();
    await expect(active.posts).toHaveLength(0);
  },
};

const final = readingScenario([]);
export const ReservedFinalSlotIsNotAnActualPassCount: Story = {
  args: {
    scenario: {
      payload: {
        reading_jobs: {
          'claude:s1': {
            ...LONG_JOB,
            progress: {
              ...EVIDENCE_PROGRESS,
              stage: 'reconciliation',
              evidence: { planned: 7, ended: 7, current: null },
              reconciliation: { ordinal: 17, state: 'running' },
              accounting: { ...EVIDENCE_PROGRESS.accounting, state: 'minimum' },
            },
          },
        },
      },
      reading: final,
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText('Final comparison')).toBeVisible();
    await expect(root).toHaveTextContent('Evidence passes finished: 7 of 7.');
    await expect(root).toHaveTextContent('Calls reserved: at least 4.');
    await expect(root.textContent).not.toMatch(/pass 17|of 8|successful/);
    await expect(final.posts).toHaveLength(0);
  },
};

const blockedCalls = readingScenario([]);
export const CleanupUnconfirmedAfterCancel: Story = {
  args: {
    scenario: {
      payload: {
        reading_jobs: {
          'claude:s1': {
            ...LONG_JOB,
            cancelling: true,
            blocked_reason: 'cleanup-unresolved',
            progress: EVIDENCE_PROGRESS,
          },
        },
      },
      reading: blockedCalls,
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(
      await within(root).findByText(
        'Compass could not confirm that the analysis process ended. It may still be running. No new result was saved. Recorded calls remain counted.',
      ),
    ).toBeVisible();
    await expect(root).toHaveTextContent('Analysis cleanup unconfirmed');
    await expect(root.textContent).not.toMatch(
      /Evidence pass 4 of 7|result will appear|Analyzing drift|process stopped/,
    );
    await expect(root).toHaveTextContent('Calls reserved: 4.');
    const cancel = await within(root).findByRole('button', { name: 'Cancel' });
    await expect(cancel).toHaveAttribute('aria-disabled', 'true');
    cancel.focus();
    await expect(cancel).toHaveFocus();
    await expect(blockedCalls.posts).toHaveLength(0);
  },
};
const unknownCalls = readingScenario([]);
export const UnknownBlockedTokenIsNotDisplayed: Story = {
  args: {
    scenario: {
      payload: {
        reading_jobs: {
          'claude:s1': {
            ...LONG_JOB,
            blocked_reason: '/raw/private/failure',
          },
        },
      },
      reading: unknownCalls,
    },
  },
  play: async ({ canvasElement }) => {
    const root = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(await within(root).findByText('Collecting source')).toBeVisible();
    await expect(root.textContent).not.toMatch(/raw.private.failure|may still be running/);
    await expect(unknownCalls.posts).toHaveLength(0);
  },
};
