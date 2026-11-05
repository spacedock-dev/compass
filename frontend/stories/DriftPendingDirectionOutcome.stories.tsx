import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import {
  DEPARTURE_READING,
  DriftScenario,
  failedCheck,
  fact,
  readingScenario,
  routeOf,
} from './drift.scenario';

/* A later user message waits for an intent decision, so the Drift card draws the direction question in the
   Analyze control's place. The last stored Analyze outcome must stay an ordinary visible paragraph there, as it
   is beside the plain control. Each play asserts the paragraph itself, not only a live-region announcement. */
const meta = {
  title: 'Drift/Pending direction keeps the last outcome',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const ROUTE = routeOf('claude', {
  provider: 'claude',
  label: 'Claude Code',
  reason: 'own-harness',
  note: "This session's own harness reads it.",
  fallback: false,
});
const REFUSED_UNSENT =
  "Nothing was sent to the model, and no Analyze attempt was counted. The assembled prompt exceeds this route's estimated allowance. Lower Prompt size in Settings or choose a route with a larger context window.";
const CANCELLED_UNSENT =
  'The analysis was cancelled before anything was sent. Nothing was sent or spent.';
const FAILED =
  'Analyze failed: Claude Code said it is not logged in. Nothing was saved. Fix that, then press Analyze drift again.';
const PENDING = [
  failedCheck('c1', 500),
  fact('u2', 1050, { type: 'user_message', by: 'person:me', summary: 'Use a different queue' }),
];

interface Held {
  readonly board: { refresh?: () => Promise<void> };
  readonly reading: ReturnType<typeof readingScenario>;
}
const held = (): Held => ({ board: {}, reading: readingScenario([]) });

const outcomes = (card: HTMLElement) => card.querySelectorAll('p.next-cockpit-reading-outcome');

/* The same words once in the card, an ordinary paragraph, and the pending decision untouched. */
const standsOnce = async (
  card: HTMLElement,
  text: string,
  press: string | RegExp = 'Analyze drift',
) => {
  const paragraphs = outcomes(card);
  await expect(paragraphs).toHaveLength(1);
  await expect(paragraphs[0]).toBeVisible();
  await expect(paragraphs[0]).toHaveTextContent(text);
  await expect(paragraphs[0]).not.toHaveAttribute('role', 'status');
  await expect(card.querySelector('[role="status"]')).toBeNull();
  await expect(card.textContent?.split(text).length).toBe(2);
  await expect(within(card).getByRole('button', { name: 'Add as a line' })).toBeVisible();
  await expect(within(card).getByRole('button', { name: 'Make it the goal' })).toBeVisible();
  await expect(within(card).getByRole('button', { name: 'Leave it' })).toBeVisible();
  await expect(within(card).getByRole('button', { name: press })).toBeVisible();
};

const unsent = held();
export const AnUnsentRefusalStaysVisibleAndSpendsNothing: Story = {
  args: {
    scenario: {
      route: ROUTE,
      reading: unsent.reading,
      board: unsent.board,
      facts: PENDING,
      session: {
        annotation_reading_count: 0,
        annotation_reading_withheld: REFUSED_UNSENT,
        annotation_reading_withheld_at: 1000,
      },
    },
  },
  play: async ({ canvasElement, args }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, REFUSED_UNSENT);
    await expect(args.scenario.session?.['annotation_reading_count']).toBe(0);
    await expect(args.scenario.session?.['annotation_assessment']).toBeUndefined();
    await expect(card.querySelector('[data-next-result]')).toBeNull();
    // A refusal the attempt never spent must not read as a counted check.
    await expect(card.querySelector('.next-cockpit-reading-count')).toBeNull();

    if (!unsent.board.refresh) throw new Error('the board refresh seam was not mounted');
    await unsent.board.refresh();
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, REFUSED_UNSENT);
    await expect(unsent.reading.posts).toHaveLength(0);
  },
};

const cancelled = held();
export const ACancellationBeforeSendStaysVisible: Story = {
  args: {
    scenario: {
      route: ROUTE,
      reading: cancelled.reading,
      board: cancelled.board,
      facts: PENDING,
      session: {
        annotation_reading_count: 0,
        annotation_reading_withheld: CANCELLED_UNSENT,
        annotation_reading_withheld_at: 1000,
      },
    },
  },
  play: async ({ canvasElement, args }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, CANCELLED_UNSENT);
    await expect(args.scenario.session?.['annotation_assessment']).toBeUndefined();
    await expect(card.querySelector('.next-cockpit-reading-count')).toBeNull();
    if (!cancelled.board.refresh) throw new Error('the board refresh seam was not mounted');
    await cancelled.board.refresh();
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, CANCELLED_UNSENT);
    await expect(cancelled.reading.posts).toHaveLength(0);
  },
};

const failed = held();
export const AFailedAnalysisStaysVisibleAndItsAttemptStaysCounted: Story = {
  args: {
    scenario: {
      route: ROUTE,
      reading: failed.reading,
      board: failed.board,
      facts: PENDING,
      session: {
        annotation_reading_count: 1,
        annotation_reading_withheld: FAILED,
        annotation_reading_withheld_at: 1000,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, FAILED);
    await expect(card.querySelector('.next-cockpit-reading-count')).toHaveTextContent(
      '1 drift check requested',
    );
    if (!failed.board.refresh) throw new Error('the board refresh seam was not mounted');
    await failed.board.refresh();
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, FAILED);
    await expect(failed.reading.posts).toHaveLength(0);
  },
};

const retained = held();
export const AFailedAttemptKeepsTheEarlierAssessmentReadable: Story = {
  args: {
    scenario: {
      route: ROUTE,
      reading: retained.reading,
      board: retained.board,
      facts: PENDING,
      session: {
        annotation_assessment: DEPARTURE_READING,
        annotation_reading_count: 2,
        annotation_reading_withheld: FAILED,
        annotation_reading_withheld_at: 1100,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, FAILED, /again/i);
    await expect(card.querySelector('[data-next-result]')).not.toBeNull();
    await expect(await within(card).findByText('It stopped running the tests.')).toBeVisible();
    if (!retained.board.refresh) throw new Error('the board refresh seam was not mounted');
    await retained.board.refresh();
    await waitFor(() => expect(outcomes(card)).toHaveLength(1));
    await standsOnce(card, FAILED, /again/i);
    await expect(await within(card).findByText('It stopped running the tests.')).toBeVisible();
    await expect(retained.reading.posts).toHaveLength(0);
  },
};
