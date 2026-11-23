import { openSessionTechnicalTab } from './sessionTechnical';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { expectSwitchPaint } from './switch.audit';
import {
  DriftScenario,
  fact,
  failedCheck,
  leaseScenario,
  leaseState,
  passedCheck,
  readingScenario,
  STORED_READING,
  analysisRow,
  type LeaseScenario,
  type Scenario,
} from './drift.scenario';

/* The Live monitor switch and what it shows, in every state a reader meets it in: off; on with the Haiku
   level, labelled the monitor's; on with the estimate as the fallback; disabled once the session has ended,
   and turning itself off, with a note, if it ends while the reader is looking; and each reason the monitor
   turns itself off. The switch drives a lease the server holds, so each story scripts the server and reads
   back what the page sent. */

const meta = {
  title: 'Drift/Live monitor',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });
const FACTS = [PERSON, failedCheck('c1', 500), passedCheck('c2', 600)];
const ESTIMATE = (level: string) => ({
  harness: 'claude',
  sid: 's1',
  revision: 3,
  computed_at: 990,
  level,
  reasons: ['pass-then-write'],
  cites: [],
});
const HAIKU = (level: string) => ({
  level,
  model_level: level,
  floor_applied: false,
  reason: 'The latest turns wrote outside the saved folders.',
  cites: [{ number: 1, fact_id: 'c1' }],
  fallback: 'medium',
  source: 'Live monitor · Haiku',
  checked_at: 1090,
});

const drawn = (canvasElement: HTMLElement) =>
  within(canvasElement).findByRole('region', { name: 'Drift' });

async function monitorSwitch(): Promise<HTMLElement> {
  await openSessionTechnicalTab('AI use and privacy');
  return within(document.body).findByRole('switch', { name: 'Live monitor' });
}
async function turnOn(): Promise<HTMLElement> {
  const toggle = await monitorSwitch();
  await userEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'));
  return toggle;
}
const actions = (lease: LeaseScenario) => lease.posts.map((post) => String(post['action']));
const pill = (card: HTMLElement) =>
  card.ownerDocument.querySelector('[data-next-drift-pill] strong')?.textContent ?? null;
const note = () => document.querySelector('[data-next-live-note]');

export const Off: Story = {
  ...scenario({
    facts: FACTS,
    work: { live_levels: [ESTIMATE('medium')] },
    lease: leaseScenario(leaseState({ level: HAIKU('high') })),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await monitorSwitch();
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(toggle).not.toHaveAttribute('aria-disabled');
    // Nothing is shown or sent while it is off, whatever the server may hold.
    await expect(pill(card)).toBeNull();
    await expect(actions(args.scenario.lease as LeaseScenario)).toEqual([]);
    const hint = document.querySelector('[data-next-live-hint]') as HTMLElement;
    await expectSwitchPaint(toggle, false);
    toggle.scrollIntoView({ block: 'center', behavior: 'instant' });
    const box = toggle.getBoundingClientRect();
    for (const y of [box.top + 0.5, box.bottom - 0.5]) {
      const hit = document.elementFromPoint(box.left + box.width / 2, y);
      await expect(toggle.contains(hit), 'Switch target in technical details').toBe(true);
    }
    await expect(hint).toHaveTextContent(/^Checks progress about once a minute while you watch$/);
    await expect(toggle).toHaveAccessibleDescription(
      /^Checks progress about once a minute while you watch Asks Haiku, through your Claude Code/,
    );
    await expect(
      within(document.body).getByText(/^Asks Haiku, through your Claude Code/),
    ).toBeVisible();
  },
};

export const OnWithTheHaikuLevel: Story = {
  ...scenario({
    facts: FACTS,
    work: { live_levels: [ESTIMATE('none_or_low')] },
    lease: leaseScenario(leaseState({ level: HAIKU('high'), now: 5000 })),
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const toggle = await monitorSwitch();
    toggle.focus();
    await userEvent.keyboard(' ');
    await waitFor(() => expect(pill(card)).toBe('High'));
    await expectSwitchPaint(toggle, true);
    await expect(card.ownerDocument.querySelector('[data-next-drift-pill]')).not.toHaveTextContent(
      'Live monitor · Haiku',
    );
    const level = card.querySelector('[data-next-drift-level]') as HTMLElement;
    await expect(level).not.toHaveTextContent('Live monitor · Haiku');
    await expect(within(document.body).getByText('Live monitor · Haiku')).toBeVisible();
    const sent = document.querySelector('[data-next-live-sent]');
    await expect(sent).toHaveTextContent('api.anthropic.com');
    await expect(sent).toHaveTextContent('the commands of tests and builds with their result');
    await expect(sent).toHaveTextContent('Pause all AI use stops it.');
  },
};

export const OnWithTheEstimateAsFallback: Story = {
  ...scenario({
    facts: FACTS,
    work: { live_levels: [ESTIMATE('medium')] },
    lease: leaseScenario(leaseState({ level: null, now: 5000 })),
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    await turnOn();
    await waitFor(() => expect(pill(card)).toBe('Medium'));
    const level = card.querySelector('[data-next-drift-level]') as HTMLElement;
    await expect(level).toHaveTextContent('Live estimate');
    await expect(level).not.toHaveTextContent('Live monitor · Haiku');
    await expect(level).toHaveTextContent('No model assessment for this intent yet');
  },
};

export const EndedAndDisabled: Story = {
  ...scenario({
    facts: FACTS,
    session: { ended_at: 500 },
    lease: leaseScenario(),
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    const toggle = await monitorSwitch();
    await expect(toggle).toHaveAttribute('aria-disabled', 'true');
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    const track = toggle.querySelector('[data-slot="switch-track"]');
    if (!track) throw new Error('Live monitor is missing its track');
    await expect(getComputedStyle(track).borderTopStyle).toBe('dashed');
    await expect(document.querySelector('[data-next-live-reason]')).toHaveTextContent(
      'The session has ended',
    );
    toggle.focus();
    await expect(toggle).toHaveFocus();
    await expect(toggle).toHaveAccessibleDescription(
      /^Checks progress about once a minute while you watch The session has ended Asks Haiku, through your Claude Code/,
    );
    await userEvent.click(toggle);
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(actions(args.scenario.lease as LeaseScenario)).toEqual([]);
  },
};

const ending = { ended_at: undefined as number | undefined };
export const EndsWhileViewed: Story = {
  ...scenario({
    facts: FACTS,
    session: ending,
    board: {},
    lease: leaseScenario(leaseState({ now: 5000 })),
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    const toggle = await turnOn();
    // The session ends while the reader is looking at it: no reload.
    ending.ended_at = 1200;
    await args.scenario.board?.refresh?.();
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'));
    await expect(toggle).toHaveAttribute('aria-disabled', 'true');
    await waitFor(() => expect(note()).toHaveTextContent(/session ended/));
    await expect(document.querySelector('[data-next-live-reason]')).toHaveTextContent(
      'The session has ended',
    );
    ending.ended_at = undefined;
  },
};

/* A lease the server ends after the reader turned it on: the next beat finds it gone, and the card says why. */
async function endsBy(reason: string, args: { readonly scenario: Scenario }): Promise<void> {
  const lease = args.scenario.lease as LeaseScenario;
  await turnOn();
  lease.state = leaseState({ on: false, last_end: { reason, at: 1200 }, now: 9000 });
  lease.beat = 'gone';
  args.scenario.clock?.advance?.(20_000);
}

export const TurnedOffBecauseTheReaderLeft: Story = {
  ...scenario({ facts: FACTS, clock: {}, lease: leaseScenario(leaseState({ now: 5000 })) }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    await endsBy('left', args);
    await waitFor(() => expect(note()).toHaveTextContent(/stopped checking in/));
    await expect(await monitorSwitch()).toHaveAttribute('aria-checked', 'false');
  },
};

export const TurnedOffBecauseModelCallsWerePaused: Story = {
  ...scenario({
    facts: FACTS,
    clock: {},
    work: { live_levels: [ESTIMATE('medium')] },
    reading: readingScenario([]),
    lease: leaseScenario(leaseState({ now: 5000 })),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await turnOn();
    // The reader pauses model calls: the page's board says so, and the server ends the lease.
    await userEvent.click(within(document.body).getByRole('switch', { name: 'Pause all AI use' }));
    const lease = args.scenario.lease as LeaseScenario;
    lease.state = leaseState({ on: false, last_end: { reason: 'paused', at: 1200 }, now: 9000 });
    lease.beat = 'gone';
    args.scenario.clock?.advance?.(20_000);
    await expect(
      within(document.body).getByRole('switch', { name: 'Resume AI use' }),
    ).toBeVisible();
    await waitFor(() =>
      expect(note()).toHaveTextContent(
        'Live monitor turned off: model calls are paused. Resume AI use, then turn it on again.',
      ),
    );
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await waitFor(() => expect(toggle).toHaveAttribute('aria-disabled', 'true'));
    await expect(document.querySelector('[data-next-live-reason]')).toHaveTextContent(
      'Model calls are paused',
    );
    // Paused is not off for the level: the estimate stays as the fallback.
    await waitFor(() => expect(pill(card)).toBe('Medium'));
  },
};

export const TurnedOffByItsOwnLimit: Story = {
  ...scenario({
    facts: FACTS,
    clock: {},
    work: { live_levels: [ESTIMATE('medium')] },
    lease: leaseScenario(leaseState({ now: 5000 })),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await endsBy('cap', args);
    await waitFor(() => expect(note()).toHaveTextContent(/its own limit of checks/));
    // Its words are the monitor's, never Analyze's cap banner.
    await expect(note()).not.toHaveTextContent(/drift analyses/);
    await expect(note()).toHaveTextContent(/not your Analyze budget/);
    // Its limit is spent, so the level is the estimate's, as before the monitor was on.
    await waitFor(() => expect(pill(card)).toBe('Medium'));
    await expect(card.querySelector('[data-next-drift-level]')).toHaveTextContent('Live estimate');
  },
};

export const RefusedToStart: Story = {
  ...scenario({
    facts: FACTS,
    lease: { ...leaseScenario(leaseState({ on: false })), refuse: 'paused' },
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    const toggle = await monitorSwitch();
    await userEvent.click(toggle);
    await waitFor(() => expect(note()).toHaveTextContent(/did not start.*paused/));
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(actions(args.scenario.lease as LeaseScenario)).toEqual(['start']);
  },
};

/* Claude Code settings the shared check refuses: the switch stays off and says why and where to look, rather
   than turning on and making no check. */
export const RefusedToStartByClaudeCodeSettings: Story = {
  ...scenario({
    facts: FACTS,
    lease: { ...leaseScenario(leaseState({ on: false })), refuse: 'settings-refused' },
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    const toggle = await monitorSwitch();
    await userEvent.click(toggle);
    await waitFor(() =>
      expect(note()).toHaveTextContent(
        'Live monitor did not start: your Claude Code settings could send its checks somewhere Compass cannot name. Nothing was sent or charged. Check the Claude Code settings your organization manages (for example apiKeyHelper, a login gateway, or telemetry that logs prompts or replies) and the folder CLAUDE_CONFIG_DIR names. Claude Code also refuses readings while its managed-mcp.json file exists. How to use Compass lists every cause under When Claude Code settings stop a check.',
      ),
    );
    await expect(note()).not.toHaveTextContent(/not available to monitor/);
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(actions(args.scenario.lease as LeaseScenario)).toEqual(['start']);
  },
};

/* Settings that change while it is on: the server refuses the next check uncharged and ends the lease with that
   reason, and the card says so instead of staying on and checking nothing. */
export const TurnedOffByClaudeCodeSettings: Story = {
  ...scenario({ facts: FACTS, clock: {}, lease: leaseScenario(leaseState({ now: 5000 })) }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    await endsBy('settings-refused', args);
    await waitFor(() =>
      expect(note()).toHaveTextContent(
        'Live monitor turned off: your Claude Code settings could send its checks somewhere Compass cannot name, so that check was not sent or charged. Check the Claude Code settings your organization manages (for example apiKeyHelper, a login gateway, or telemetry that logs prompts or replies) and the folder CLAUDE_CONFIG_DIR names. Claude Code also refuses readings while its managed-mcp.json file exists. How to use Compass lists every cause under When Claude Code settings stop a check.',
      ),
    );
    await expect(await monitorSwitch()).toHaveAttribute('aria-checked', 'false');
  },
};

export const AnalyzeOutranksTheMonitor: Story = {
  ...scenario({
    facts: FACTS,
    session: STORED_READING,
    work: {
      live_levels: [ESTIMATE('none_or_low')],
      analysis_levels: [analysisRow('claude', 'medium')],
    },
    lease: leaseScenario(leaseState({ level: HAIKU('extreme'), now: 5000 })),
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    await turnOn();
    await waitFor(() => expect(pill(card)).toBe('Medium'));
    await expect(card.ownerDocument.querySelector('[data-next-drift-pill]')).not.toHaveTextContent(
      'Live monitor',
    );
    await expect(card).not.toHaveTextContent('Live monitor · Haiku');
  },
};

export const HiddenTabHoldsTheLeaseAndResumes: Story = {
  ...scenario({
    facts: FACTS,
    clock: {},
    tab: {},
    lease: leaseScenario(leaseState({ now: 5000 })),
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    await turnOn();
    const lease = args.scenario.lease as LeaseScenario;
    const beats = () =>
      lease.posts.filter((post) => post['action'] === 'beat').map((post) => post['visible']);
    args.scenario.tab?.hide?.();
    await waitFor(() => expect(beats()).toEqual([false]));
    args.scenario.clock?.advance?.(120_000);
    await expect(beats()).toEqual([false]);
    args.scenario.tab?.show?.();
    await waitFor(() => expect(beats()).toEqual([false, true]));
    args.scenario.clock?.advance?.(20_000);
    await waitFor(() => expect(beats()).toEqual([false, true, true]));
  },
};

export const StartedFromAHiddenTab: Story = {
  ...scenario({
    facts: FACTS,
    clock: {},
    tab: {},
    lease: leaseScenario(leaseState({ now: 5000 })),
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    const toggle = await monitorSwitch();
    args.scenario.tab?.hide?.();
    await userEvent.click(toggle);
    const lease = args.scenario.lease as LeaseScenario;
    await waitFor(() => expect(lease.posts[0]).toMatchObject({ action: 'start', visible: false }));
    args.scenario.clock?.advance?.(120_000);
    // Told once that the tab is hidden, and never a beat that says it is visible.
    await waitFor(() => expect(actions(lease)).toEqual(['start', 'beat']));
    await expect(lease.posts[1]).toMatchObject({ visible: false });
  },
};

export const LeftWhileTheStartWasInFlight: Story = {
  ...scenario({
    facts: FACTS,
    clock: {},
    nav: {},
    lease: { ...leaseScenario(leaseState({ now: 5000 })), hold: true },
  }),
  play: async ({ canvasElement, args }) => {
    await drawn(canvasElement);
    const toggle = await monitorSwitch();
    await userEvent.click(toggle);
    const lease = args.scenario.lease as LeaseScenario;
    await waitFor(() => expect(actions(lease)).toEqual(['start']));
    // The reader leaves for another page before the server has answered.
    args.scenario.nav?.go?.('#n=intent');
    await waitFor(() =>
      expect(document.querySelector('[data-next-cockpit-action="live-monitor"]')).toBeNull(),
    );
    lease.release?.();
    // The lease the server made after they had gone is stopped, so no check is made for it.
    await waitFor(() => expect(actions(lease)).toEqual(['start', 'stop']));
  },
};
