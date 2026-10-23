import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import {
  DriftScenario,
  fact,
  failedCheck,
  leaseScenario,
  leaseState,
  passedCheck,
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
const head = (card: HTMLElement) => card.querySelector('header') as HTMLElement;

async function monitorSwitch(card: HTMLElement): Promise<HTMLElement> {
  await userEvent.click(within(head(card)).getByRole('button', { name: 'Drift settings' }));
  return within(document.body).findByRole('switch', { name: 'Live monitor' });
}
async function turnOn(card: HTMLElement): Promise<HTMLElement> {
  const toggle = await monitorSwitch(card);
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
    const toggle = await monitorSwitch(card);
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(toggle).not.toHaveAttribute('aria-disabled');
    // Nothing is shown or sent while it is off, whatever the server may hold.
    await expect(pill(card)).toBeNull();
    await expect(actions(args.scenario.lease as LeaseScenario)).toEqual([]);
    // The hint names the model call, how often it runs and where the text goes.
    const hint = document.querySelector('[data-next-live-hint]') as HTMLElement;
    await expect(hint).toHaveTextContent(/Haiku/);
    await expect(hint).toHaveTextContent(/about once a minute/);
    await expect(hint).toHaveTextContent(/Claude Code/);
    await expect(hint).not.toHaveTextContent(/no model call/);
  },
};

export const OnWithTheHaikuLevel: Story = {
  ...scenario({
    facts: FACTS,
    work: { live_levels: [ESTIMATE('none_or_low')] },
    lease: leaseScenario(leaseState({ level: HAIKU('high'), now: 5000 })),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await turnOn(card);
    await waitFor(() => expect(pill(card)).toBe('High'));
    const level = card.querySelector('[data-next-drift-level]') as HTMLElement;
    await expect(level).toHaveTextContent('Live monitor · Haiku');
    await expect(level).toHaveTextContent('The latest turns wrote outside the saved folders.');
    await expect(level).not.toHaveTextContent('Live estimate');
    await expect(actions(args.scenario.lease as LeaseScenario)[0]).toBe('start');
    // The server's own words about what is sent stand under the switch while it is on.
    await expect(document.querySelector('[data-next-live-sent]')).toHaveTextContent(
      'api.anthropic.com',
    );
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
    await turnOn(card);
    await waitFor(() => expect(pill(card)).toBe('Medium'));
    const level = card.querySelector('[data-next-drift-level]') as HTMLElement;
    await expect(level).toHaveTextContent('Live estimate');
    await expect(level).not.toHaveTextContent('Live monitor · Haiku');
  },
};

export const EndedAndDisabled: Story = {
  ...scenario({
    facts: FACTS,
    session: { ended_at: 500 },
    lease: leaseScenario(),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await monitorSwitch(card);
    await expect(toggle).toHaveAttribute('aria-disabled', 'true');
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(document.querySelector('[data-next-live-reason]')).toHaveTextContent(
      'The session has ended',
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
    const card = await drawn(canvasElement);
    const toggle = await turnOn(card);
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
async function endsBy(
  reason: string,
  args: { readonly scenario: Scenario },
  card: HTMLElement,
): Promise<void> {
  const lease = args.scenario.lease as LeaseScenario;
  await turnOn(card);
  lease.state = leaseState({ on: false, last_end: { reason, at: 1200 }, now: 9000 });
  lease.beat = 'gone';
  args.scenario.clock?.advance?.(20_000);
}

export const TurnedOffBecauseTheReaderLeft: Story = {
  ...scenario({ facts: FACTS, clock: {}, lease: leaseScenario(leaseState({ now: 5000 })) }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await endsBy('left', args, card);
    await waitFor(() => expect(note()).toHaveTextContent(/left the session or this tab stopped/));
    await expect(await monitorSwitch(card)).toHaveAttribute('aria-checked', 'false');
  },
};

export const TurnedOffBecauseModelCallsWerePaused: Story = {
  ...scenario({ facts: FACTS, clock: {}, lease: leaseScenario(leaseState({ now: 5000 })) }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await endsBy('paused', args, card);
    await waitFor(() => expect(note()).toHaveTextContent(/model calls are paused/));
  },
};

export const TurnedOffByItsOwnLimit: Story = {
  ...scenario({ facts: FACTS, clock: {}, lease: leaseScenario(leaseState({ now: 5000 })) }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await endsBy('cap', args, card);
    await waitFor(() => expect(note()).toHaveTextContent(/its own limit of checks/));
    // Its words are the monitor's, never Analyze's cap banner.
    await expect(note()).not.toHaveTextContent(/drift analyses/);
    await expect(note()).toHaveTextContent(/not your Analyze budget/);
  },
};

export const RefusedToStart: Story = {
  ...scenario({
    facts: FACTS,
    lease: { ...leaseScenario(leaseState({ on: false })), refuse: 'paused' },
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await monitorSwitch(card);
    await userEvent.click(toggle);
    await waitFor(() => expect(note()).toHaveTextContent(/did not start.*paused/));
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(actions(args.scenario.lease as LeaseScenario)).toEqual(['start']);
  },
};
