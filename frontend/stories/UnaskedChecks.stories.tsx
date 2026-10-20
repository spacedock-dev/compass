import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { DriftScenario, readingScenario, routeOf, type Scenario } from './drift.scenario';

const meta = { title: 'Drift/Unasked check permission', component: DriftScenario } satisfies Meta<
  typeof DriftScenario
>;
export default meta;
type Story = StoryObj<typeof meta>;
const route = {
  ...routeOf('codex', {
    provider: 'codex',
    label: 'Codex',
    reason: 'own-harness',
    note: 'This session’s own harness reads it.',
    fallback: false,
  }),
  disclosure_parts: [
    'Sent: your typed goal and bounded user messages. No agent messages, tool output or outcome lines.',
    'To: OpenAI through your Codex CLI, spending your capacity.',
  ],
};
const scenario = (patch: Partial<Scenario> = {}): Scenario => ({
  harness: 'codex',
  route,
  payload: {
    unasked: true,
    unasked_routes: { codex: route },
    reading: { consent: true, off: false, reason: '', words: { codex: false } },
  },
  ...patch,
});
const off = 'Allow Codex to run unasked checks';
const on = off;

export const WaitingWithToggleOff: Story = {
  args: { scenario: scenario() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole('switch', { name: off })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    await expect(
      canvas.getByText(/Unasked checks of this session are waiting for your permission/),
    ).toBeVisible();
  },
};

const granting = readingScenario([]);
export const Granting: Story = {
  args: { scenario: scenario({ reading: granting }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('switch', { name: off }));
    await expect(await canvas.findByRole('switch', { name: on })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await expect(granting.posts).toHaveLength(1);
    await expect(granting.posts[0]).toMatchObject({
      unasked_grant: true,
      provider: 'codex',
      words_destination: 'api',
      press: true,
    });
  },
};

const revoking = readingScenario([]);
export const Revoking: Story = {
  args: {
    scenario: scenario({
      reading: revoking,
      payload: {
        unasked: true,
        unasked_routes: { codex: route },
        reading: { consent: true, words: { codex: true } },
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole('switch', { name: on });
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByText(/Turn the switch off to revoke it/)).toBeVisible();
    await userEvent.click(toggle);
    await expect(await canvas.findByRole('switch', { name: off })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    await expect(revoking.posts).toHaveLength(1);
    await expect(revoking.posts[0]).toMatchObject({ unasked_grant: false });
  },
};

export const FlagOff: Story = {
  args: { scenario: scenario({ payload: { unasked: false } }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('region', { name: 'Drift' });
    await expect(canvas.queryByRole('switch', { name: off })).toBeNull();
  },
};

export const FlagOffOnAttention: Story = {
  args: { scenario: scenario({ initialView: 'attention', payload: { unasked: false } }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('OBSERVED', { exact: true });
    await expect(
      canvas.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
  },
};

export const Paused: Story = {
  args: {
    scenario: scenario({
      payload: {
        unasked: true,
        unasked_routes: { codex: route },
        reading: {
          consent: false,
          off: true,
          reason: 'model-calls-paused',
          words: { codex: false },
        },
      },
    }),
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole('switch', { name: off })).toBeDisabled();
    await expect(
      within(canvasElement).getByRole('region', { name: 'Unasked checks' }),
    ).toHaveTextContent(/paused/i);
  },
};

const claudeRoute = routeOf('claude', {
  provider: 'claude',
  label: 'Claude Code',
  reason: 'own-harness',
  note: 'This session’s own harness reads it.',
  fallback: false,
});
export const ClaudeNeedsNoToggle: Story = {
  args: { scenario: { payload: { unasked: true, unasked_routes: { claude: claudeRoute } } } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('region', { name: 'Drift' });
    await expect(canvas.queryByRole('switch', { name: off })).toBeNull();
  },
};

export const AttentionPointsToTheToggle: Story = {
  args: { scenario: scenario({ initialView: 'attention' }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const cue = await canvas.findByRole('region', {
      name: 'Unasked checks waiting for permission',
    });
    await expect(cue).toHaveTextContent('Allow Codex to run unasked checks');
    await userEvent.click(within(cue).getByRole('link', { name: 'Synthetic session' }));
    await expect(await canvas.findByRole('switch', { name: off })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  },
};

export const AttentionCueWaiting: Story = {
  args: { scenario: scenario({ initialView: 'attention' }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const cue = await canvas.findByRole('region', {
      name: 'Unasked checks waiting for permission',
    });
    await expect(cue).toHaveTextContent('Codex needs your permission first');
    await expect(within(cue).getByRole('link', { name: 'Synthetic session' })).toBeVisible();
  },
};
