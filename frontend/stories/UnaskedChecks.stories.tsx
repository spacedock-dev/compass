import dormantBoard from '../test/fixtures/client-contract/data-unasked-dormant.json';
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
  args: {
    scenario: {
      payload: {
        unasked: true,
        unasked_routes: { claude: claudeRoute },
        // No stored Codex grant, so nothing is left to revoke.
        reading: { consent: true, off: false, reason: '', words: { codex: false } },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('region', { name: 'Drift' });
    await expect(canvas.queryByRole('switch', { name: off })).toBeNull();
    // Named, with what each check sends, so a reader who turned the lane on sees where words go.
    const notice = await canvas.findByRole('region', { name: 'Unasked checks by Claude Code' });
    await expect(notice).toBeVisible();
    await expect(notice).toHaveTextContent('Claude Code checks this session');
    await expect(notice).toHaveTextContent('Your saved words.');
  },
};

const revokingAfterMove = readingScenario([]);
export const RevokeAfterClaudeTookTheRoute: Story = {
  args: {
    scenario: {
      reading: revokingAfterMove,
      payload: {
        unasked: true,
        unasked_routes: { claude: claudeRoute },
        reading: { consent: true, off: false, reason: '', words: { codex: true } },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole('switch', { name: on });
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByText(/though it does not check this session/)).toBeVisible();
    await userEvent.click(toggle);
    await expect(revokingAfterMove.posts).toHaveLength(1);
    await expect(revokingAfterMove.posts[0]).toMatchObject({
      unasked_grant: false,
      provider: 'codex',
    });
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
    await expect(cue).toHaveTextContent('none of them has been checked yet');
    await expect(within(cue).getByRole('link', { name: 'Synthetic session' })).toBeVisible();
  },
};

export const AttentionCueAfterARevoke: Story = {
  args: { scenario: scenario({ initialView: 'attention', session: { departure_checked: true } }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const cue = await canvas.findByRole('region', {
      name: 'Unasked checks waiting for permission',
    });
    // Checked before the revoke, so the cue may not say nothing was checked.
    await expect(cue).toHaveTextContent('they are not being checked now');
    await expect(cue).not.toHaveTextContent('none of them has been checked');
  },
};

const unavailable = routeOf('gemini', {
  provider: '',
  label: '',
  reason: 'no-record-reader',
  note: 'Compass cannot run unasked checks for this harness because it has no session record reader.',
  fallback: false,
});
const unreadable = (allowed = false, reading?: Scenario['reading']): Scenario => ({
  harness: 'gemini',
  ...(reading ? { reading } : {}),
  payload: {
    unasked: true,
    unasked_routes: { gemini: unavailable },
    reading: { consent: true, off: false, words: { codex: allowed } },
  },
});

export const NoSessionRecordReader: Story = {
  args: { scenario: unreadable() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(String(unavailable['note']))).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: off })).toBeNull();
  },
};

export const UnreadableSessionIsAbsentFromAttention: Story = {
  args: { scenario: { ...unreadable(), initialView: 'attention' } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('OBSERVED', { exact: true });
    await expect(
      canvas.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
    ).toBeNull();
  },
};

const unreadableRevoke = readingScenario([]);
export const UnreadableSessionKeepsRevocation: Story = {
  args: { scenario: unreadable(true, unreadableRevoke) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(String(unavailable['note']))).toBeVisible();
    const toggle = canvas.getByRole('switch', { name: off });
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(toggle);
    await expect(unreadableRevoke.posts).toHaveLength(1);
    await expect(unreadableRevoke.posts[0]).toMatchObject({ unasked_grant: false });
    await expect(canvas.queryByRole('switch', { name: off })).toBeNull();
    await expect(canvas.getByText(String(unavailable['note']))).toBeVisible();
  },
};

function supported(harness: 'pi' | 'antigravity'): Story {
  return {
    args: {
      scenario: scenario({
        harness,
        initialView: 'attention',
        payload: {
          unasked: true,
          unasked_routes: { [harness]: { ...route, harness, reason: 'fallback-not-installed' } },
          reading: { consent: true, off: false, words: { codex: false } },
        },
      }),
    },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const cue = await canvas.findByRole('region', {
        name: 'Unasked checks waiting for permission',
      });
      await expect(cue).toHaveTextContent('Codex needs your permission first');
      await userEvent.click(within(cue).getByRole('link', { name: 'Synthetic session' }));
      await expect(await canvas.findByRole('switch', { name: off })).toHaveAttribute(
        'aria-checked',
        'false',
      );
    },
  };
}
export const PiKeepsPermission = supported('pi');
export const AntigravityKeepsPermission = supported('antigravity');

const dormantNote = dormantBoard.response.body.reading.dormant.codex;
function dormantStory(
  harness: 'codex' | 'claude' | 'gemini',
  unaskedRoute: Record<string, unknown>,
): Story {
  const revoke = readingScenario([]);
  return {
    args: {
      scenario: {
        harness,
        reading: revoke,
        payload: {
          unasked: true,
          unasked_routes: { [harness]: unaskedRoute },
          reading: dormantBoard.response.body.reading,
        },
      },
    },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const toggle = await canvas.findByRole('switch', { name: off });
      await expect(toggle).toHaveAttribute('aria-checked', 'true');
      await expect(canvas.getByText(dormantNote, { exact: true })).toBeVisible();
      await expect(canvas.queryByText(/allow it again/i)).toBeNull();
      await expect(canvas.queryByText(/This permission covers every session/)).toBeNull();
      if (harness === 'gemini')
        await expect(canvas.getByText(String(unavailable['note']))).toBeVisible();
      if (harness === 'claude')
        await expect(
          canvas.getByRole('region', { name: 'Unasked checks by Claude Code' }),
        ).toBeVisible();
      await userEvent.click(toggle);
      await expect(revoke.posts).toHaveLength(1);
      await expect(revoke.posts[0]).toMatchObject({ unasked_grant: false, provider: 'codex' });
      await expect(revoke.posts.some((post) => post['unasked_grant'] === true)).toBe(false);
      await expect(canvas.queryByText(dormantNote)).toBeNull();
      if (harness === 'codex')
        await expect(canvas.getByRole('switch', { name: off })).toHaveAttribute(
          'aria-checked',
          'false',
        );
      else await expect(canvas.queryByRole('switch', { name: off })).toBeNull();
    },
  };
}
export const ReaderRevokesDormantGrantOnCodex = dormantStory('codex', route);
export const ReaderRevokesDormantGrantOnClaude = dormantStory('claude', claudeRoute);
export const ReaderRevokesDormantGrantOnUnreadable = dormantStory('gemini', unavailable);
function attentionWithGrant(reading: Record<string, unknown>): Story {
  return {
    args: {
      scenario: scenario({
        initialView: 'attention',
        payload: { unasked: true, unasked_routes: { codex: route }, reading },
      }),
    },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      await canvas.findByRole('heading', { name: /^Attention$/ });
      await expect(
        canvas.queryByRole('region', { name: 'Unasked checks waiting for permission' }),
      ).toBeNull();
    },
  };
}
export const AttentionDoesNotInviteReaderWithDormantGrant = attentionWithGrant(
  dormantBoard.response.body.reading,
);
export const AttentionDoesNotInviteReaderWithCoveredGrant = attentionWithGrant({
  consent: true,
  off: false,
  words: { codex: true },
});
