import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { DriftScenario, fact, readingScenario, routeOf } from './drift.scenario';

const meta = {
  title: 'Drift/Next prompt allowance',
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
const PREVIEW = {
  kind: 'capacity-preview',
  policy: 'analyze-context-v1',
  maximum_prompt_bytes: 524288,
  window_tokens: null,
  window_source: 'unknown',
  generation_reserve_tokens: 128000,
  cli_reserve_tokens: 16384,
  estimated_system_tokens: 0,
  estimate_method: 'legacy-byte-cap',
  fit_verified: false,
  policy_verified: false,
  configuration_reason: '',
  reason: 'estimated',
  can_lower_prompt_setting: true,
};

/* The published producer refusal, not a synchronous HTTP policy rejection. The real job can collect
   evidence before admission refuses the assembled prompt; this story starts with HTTP 202 and waits
   for that job to disappear with its stored outcome. Backend tests establish the unspent model seam. */
const REFUSAL =
  "Nothing was sent to the model, and no Analyze attempt was counted. The assembled prompt exceeds this route's estimated allowance. Lower Prompt size in Settings or choose a route with a larger context window.";
const SESSION: Record<string, unknown> = { annotation_reading_count: 0 };
const READING = readingScenario([null]);
const BOARD: { refresh?: () => Promise<void> } = {};

export const AnUnsentPromptKeepsItsRefusalAndCountsNoAnalysis: Story = {
  args: {
    scenario: {
      route: { ...ROUTE, capacity: PREVIEW },
      session: SESSION,
      reading: READING,
      board: BOARD,
      facts: [fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' })],
    },
  },
  beforeEach: () => {
    delete SESSION['annotation_reading_withheld'];
    delete SESSION['annotation_reading_withheld_at'];
  },
  play: async ({ canvasElement, args }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    const allowance = card.querySelector('[data-next-reading-allowance]');
    await expect(allowance).toBeVisible();
    await expect(allowance).toHaveTextContent('Next Analyze prompt: Estimated allowance: 512 KB.');
    await expect(allowance).toHaveTextContent('not automatically shortened');
    await expect(allowance).toHaveTextContent(
      'do not confirm model availability or that a prompt will fit',
    );
    await userEvent.click(await within(card).findByRole('button', { name: 'Analyze drift' }));
    await waitFor(() => expect(card.querySelector('[data-next-analyzing]')).toBeVisible());
    await expect(READING.posts).toHaveLength(1);
    await expect(card.querySelector('p.next-cockpit-reading-outcome')).toBeNull();

    SESSION['annotation_reading_withheld'] = REFUSAL;
    SESSION['annotation_reading_withheld_at'] = 1000;
    if (!READING.finish) throw new Error('the asynchronous reading scenario was not mounted');
    await READING.finish();
    await waitFor(() => {
      expect(card.querySelector('[data-next-analyzing]')).toBeNull();
      // The ordinary persisted paragraph must be visible; a live-region announcement alone is not enough.
      expect(card.querySelector('p.next-cockpit-reading-outcome')).toBeVisible();
      expect(card.querySelector('p.next-cockpit-reading-outcome')).toHaveTextContent(REFUSAL);
    });
    await expect(card.querySelector('p.next-cockpit-reading-outcome')).not.toHaveAttribute(
      'role',
      'status',
    );
    await expect(args.scenario.session?.['annotation_reading_count']).toBe(0);
    await expect(args.scenario.session?.['annotation_assessment']).toBeUndefined();
    await expect(card.querySelector('[data-next-result]')).toBeNull();
    await expect(card.querySelector('.next-cockpit-reading-count')).toBeNull();
    await expect(within(card).getByRole('button', { name: 'Analyze drift' })).toBeVisible();

    if (!BOARD.refresh) throw new Error('the board refresh seam was not mounted');
    await BOARD.refresh();
    await waitFor(() =>
      expect(card.querySelector('p.next-cockpit-reading-outcome')).toHaveTextContent(REFUSAL),
    );
    await expect(card.querySelector('[data-next-reading-allowance]')).toHaveTextContent(
      'Next Analyze prompt: Estimated allowance: 512 KB.',
    );
    await expect(READING.posts).toHaveLength(1);
  },
};

export const AnOlderServerLeavesTheNextAllowanceUnknown: Story = {
  args: { scenario: { route: ROUTE } },
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Drift' });
    const allowance = card.querySelector('[data-next-reading-allowance]');
    await expect(allowance).toBeVisible();
    await expect(allowance).toHaveTextContent('Next Analyze prompt: Allowance unknown.');
    await expect(allowance).not.toHaveTextContent(/0 KB|refused before a model call/);
    await expect(await within(card).findByRole('button', { name: 'Analyze drift' })).toBeVisible();
  },
};
