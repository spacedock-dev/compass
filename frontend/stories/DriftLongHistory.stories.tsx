import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { HISTORY_ITEM, LONG_HISTORY } from '../test/longHistory';
import { DriftScenario, readingScenario, type Scenario } from './drift.scenario';

const meta = {
  title: 'Drift/Unfinished long analysis records',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;
const reading = readingScenario([]);
const exact: NonNullable<Scenario['longHistory']> = {
  value: LONG_HISTORY,
  gets: 0,
  posts: [],
  discard: { body: { ok: true, discarded: true, reason: 'receipt-unresolved' }, status: 200 },
};
export const ExplicitInspectionAndConfirmedRemoval: Story = {
  args: { scenario: { longHistory: exact, reading } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const opener = await canvas.findByRole('button', { name: 'Unfinished long analysis records' });
    await expect(exact.gets).toBe(0);
    await expect(exact.posts).toHaveLength(0);
    await userEvent.click(opener);
    await waitFor(() =>
      expect(canvas.getByText(/Exact recorded accounting: 4 calls/)).toBeVisible(),
    );
    await expect(canvas.getByText(/does not establish whether a process is alive/)).toBeVisible();
    await expect(canvas.getByText(/cannot stop a model or refund calls/)).toBeVisible();
    await expect(exact.gets).toBe(1);
    await expect(exact.posts).toHaveLength(0);
    await userEvent.click(
      canvas.getByRole('button', { name: 'Check and discard superseded record' }),
    );
    await expect(
      await canvas.findByText(/record was removed.*cleanup remains unconfirmed/),
    ).toBeVisible();
    await expect(exact.posts).toHaveLength(1);
    await expect(exact.posts[0]).toEqual({
      harness: 'claude',
      sid: 's1',
      job: HISTORY_ITEM.job_id,
      press: true,
      observer_model: 1,
    });
    await expect(
      canvas.queryByRole('button', { name: 'Check and discard superseded record' }),
    ).toBeNull();
    await waitFor(() =>
      expect(canvas.getByRole('button', { name: 'Refresh recovery records' })).toHaveFocus(),
    );
    await expect(exact.gets).toBe(1);
    await expect(reading.posts).toHaveLength(0);
  },
};
const uncertain: NonNullable<Scenario['longHistory']> = {
  value: {
    ...LONG_HISTORY,
    incomplete: true,
    reason: 'accounting-unavailable',
    items: [
      { ...HISTORY_ITEM, accounting: 'minimum', exact: null },
      {
        ...HISTORY_ITEM,
        job_id: 'b'.repeat(32),
        accounting: 'unknown',
        exact: null,
        minimum: null,
        unsettled: null,
      },
    ],
  },
  gets: 0,
  posts: [],
  discard: { body: { ok: false, discarded: false, reason: 'accounting-unknown' }, status: 409 },
};
export const MinimumAndUnknownAreRetained: Story = {
  args: { scenario: { longHistory: uncertain, reading, unsaved: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole('button', { name: 'Unfinished long analysis records' }),
    );
    await waitFor(() =>
      expect(canvas.getByText(/Minimum recorded accounting: at least 4 calls/)).toBeVisible(),
    );
    await expect(canvas.getByText(/Recorded accounting: unknown/)).toBeVisible();
    await expect(canvas.getByText(/inspection is incomplete/)).toBeVisible();
    await expect(
      canvas.queryByRole('button', { name: 'Check and discard superseded record' }),
    ).toBeNull();
    await expect(uncertain.posts).toHaveLength(0);
    await expect(reading.posts).toHaveLength(0);
  },
};
const refused: NonNullable<Scenario['longHistory']> = {
  ...exact,
  gets: 0,
  posts: [],
  discard: { body: { ok: false, discarded: false, reason: 'owner-current' }, status: 409 },
};
export const ServerRefusalKeepsTheRecord: Story = {
  args: { scenario: { longHistory: refused, reading } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole('button', { name: 'Unfinished long analysis records' }),
    );
    await userEvent.click(
      await canvas.findByRole('button', { name: 'Check and discard superseded record' }),
    );
    await waitFor(() => expect(canvas.getByText(/server did not confirm a discard/)).toBeVisible());
    await expect(canvas.getByText(/Exact recorded accounting: 4 calls/)).toBeVisible();
    await expect(refused.posts).toHaveLength(1);
    await expect(refused.gets).toBe(1);
    await expect(reading.posts).toHaveLength(0);
  },
};
