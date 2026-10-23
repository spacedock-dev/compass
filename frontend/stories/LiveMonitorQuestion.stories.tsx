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

/* "Do you still want to monitor this session?" The server holds the clock and publishes `confirm_by` from 20
   minutes after the monitor started, or after the last Yes, until 10 minutes later. Each story scripts that
   server and moves the page's clock: the question opens and counts down, Yes resets it and the next comes later,
   No turns the monitor off, no answer turns it off with a note, another end clears it and shows its own note,
   and it is announced and reachable by keyboard. */

const meta = {
  title: 'Drift/Live monitor question',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const FACTS = [
  fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' }),
  failedCheck('c1', 500),
  passedCheck('c2', 600),
];

/* The server's state while the question stands: due at 1100, open until 1700, the page clock at 1000 so each
   advance of the page's clock counts the deadline down. */
const asking = (over: Record<string, unknown> = {}) =>
  leaseState({ banner_due_at: 1100, deadline: 1700, confirm_by: 1700, now: 1120, ...over });

const drawn = (canvasElement: HTMLElement) =>
  within(canvasElement).findByRole('region', { name: 'Drift' });
const head = (card: HTMLElement) => card.querySelector('header') as HTMLElement;
const banner = () => document.querySelector<HTMLElement>('[data-next-live-question]');
const note = () => document.querySelector('[data-next-live-note]');

async function monitoring(card: HTMLElement): Promise<HTMLElement> {
  await userEvent.click(within(head(card)).getByRole('button', { name: 'Drift settings' }));
  const toggle = await within(document.body).findByRole('switch', { name: 'Live monitor' });
  await userEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'true'));
  return toggle;
}

/* The question opens on the next beat, as the server then publishes it. */
async function opens(
  args: { readonly scenario: Scenario },
  card: HTMLElement,
): Promise<HTMLElement> {
  const toggle = await monitoring(card);
  (args.scenario.lease as LeaseScenario).state = asking();
  args.scenario.clock?.advance?.(20_000);
  await waitFor(() => expect(banner()).not.toBeNull());
  return toggle;
}

const readyScenario = (over: Partial<LeaseScenario> = {}): Pick<Story, 'args'> =>
  scenario({
    facts: FACTS,
    clock: {},
    lease: { ...leaseScenario(leaseState({ now: 1050 })), ...over },
  });

export const OpensAndCountsDownTen: Story = {
  ...readyScenario(),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await expect(banner()).toBeNull();
    await opens(args, card);
    const question = banner() as HTMLElement;
    await expect(
      within(question).getByText('Do you still want to monitor this session?'),
    ).toBeVisible();
    await expect(within(question).getByRole('button', { name: 'Yes' })).toBeVisible();
    await expect(within(question).getByRole('button', { name: 'No' })).toBeVisible();
    await expect(question).toHaveTextContent('9m 40s');
    args.scenario.clock?.advance?.(60_000);
    await waitFor(() => expect(question).toHaveTextContent('8m 40s'));
    args.scenario.clock?.advance?.(300_000);
    await waitFor(() => expect(question).toHaveTextContent('3m 40s'));
  },
};

export const YesResetsItAndTheNextComesLater: Story = {
  ...readyScenario({
    onConfirm: () =>
      leaseState({ confirm_by: null, banner_due_at: 2330, deadline: 2930, now: 1130 }),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await opens(args, card);
    await userEvent.click(within(banner() as HTMLElement).getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(banner()).toBeNull());
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await expect(note()).toBeNull();
    const lease = args.scenario.lease as LeaseScenario;
    await expect(lease.posts.map((post) => post['action'])).toContain('confirm');
    // The next question is the server's to open, twenty minutes on.
    lease.state = asking({ banner_due_at: 2330, deadline: 2930, confirm_by: 2930, now: 2340 });
    args.scenario.clock?.advance?.(20_000);
    await waitFor(() => expect(banner()).not.toBeNull());
  },
};

export const NoTurnsItOff: Story = {
  ...readyScenario({
    onConfirm: () =>
      leaseState({
        on: false,
        confirm_by: null,
        last_end: { reason: 'declined', at: 1130 },
        now: 1130,
      }),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await opens(args, card);
    await userEvent.click(within(banner() as HTMLElement).getByRole('button', { name: 'No' }));
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'));
    await expect(banner()).toBeNull();
    await waitFor(() => expect(note()).toHaveTextContent(/turned off, as you asked/));
    // An off the reader asked for shows nothing live, as an off switch always did.
    await expect(card.ownerDocument.querySelector('[data-next-drift-pill]')).toBeNull();
  },
};

export const NoAnswerTurnsItOffWithANote: Story = {
  ...readyScenario(),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    const toggle = await opens(args, card);
    // The question runs down on the page's clock; the server, which holds the deadline, ends the monitor
    // at the same moment, and the page asks it once at that moment and takes its answer.
    args.scenario.clock?.advance?.(560_000);
    const lease = args.scenario.lease as LeaseScenario;
    lease.state = leaseState({
      on: false,
      confirm_by: null,
      last_end: { reason: 'unanswered', at: 1700 },
      now: 1700,
    });
    lease.beat = 'gone';
    args.scenario.clock?.advance?.(30_000);
    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'));
    await expect(banner()).toBeNull();
    await waitFor(() =>
      expect(note()).toHaveTextContent(
        'Live monitor turned off: no answer after 10 minutes, so no more model calls were made.',
      ),
    );
  },
};

async function clearedBy(
  reason: string,
  pattern: RegExp,
  args: { readonly scenario: Scenario },
  card: HTMLElement,
) {
  const toggle = await opens(args, card);
  const lease = args.scenario.lease as LeaseScenario;
  lease.state = leaseState({
    on: false,
    confirm_by: null,
    last_end: { reason, at: 1300 },
    now: 1300,
  });
  lease.beat = 'gone';
  args.scenario.clock?.advance?.(20_000);
  await waitFor(() => expect(banner()).toBeNull());
  await waitFor(() => expect(note()).toHaveTextContent(pattern));
  await expect(note()).not.toHaveTextContent(/no answer after/);
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
}

export const ClearedWhenTheReaderLeft: Story = {
  ...readyScenario(),
  play: async ({ canvasElement, args }) => {
    await clearedBy('left', /stopped checking in/, args, await drawn(canvasElement));
  },
};
export const ClearedWhenTheSessionEnded: Story = {
  ...readyScenario(),
  play: async ({ canvasElement, args }) => {
    await clearedBy('ended', /session ended/, args, await drawn(canvasElement));
  },
};
export const ClearedWhenModelCallsWerePaused: Story = {
  ...readyScenario(),
  play: async ({ canvasElement, args }) => {
    await clearedBy('paused', /model calls are paused/, args, await drawn(canvasElement));
  },
};

export const AnnouncedAndReachableByKeyboard: Story = {
  ...readyScenario({
    onConfirm: () =>
      leaseState({ confirm_by: null, banner_due_at: 2330, deadline: 2930, now: 1130 }),
  }),
  play: async ({ canvasElement, args }) => {
    const card = await drawn(canvasElement);
    await opens(args, card);
    const cue = document.getElementById('next-cockpit-cue-status') as HTMLElement;
    await waitFor(() =>
      expect(cue).toHaveTextContent(
        /Do you still want to monitor this session\? .*turns off in 9 minutes/,
      ),
    );
    const yes = within(banner() as HTMLElement).getByRole('button', { name: 'Yes' });
    // From the top of the page, as a keyboard reader arrives: the question is reached by Tab alone.
    (document.activeElement as HTMLElement | null)?.blur();
    for (let presses = 0; presses < 80 && document.activeElement !== yes; presses += 1) {
      await userEvent.tab();
    }
    await expect(yes).toHaveFocus();
    await userEvent.tab();
    const no = within(banner() as HTMLElement).getByRole('button', { name: 'No' });
    await expect(no).toHaveFocus();
    // Enter on Yes answers it, and focus lands on the switch the question was about.
    yes.focus();
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(banner()).toBeNull());
    const toggle = within(document.body).getByRole('switch', { name: 'Live monitor' });
    await waitFor(() => expect(toggle).toHaveFocus());
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
  },
};
