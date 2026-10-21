import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { JOB_TITLE, LIVE_HINT, RESULT_DEPARTS } from '../src/drift/sentences';
import { neverDone } from './drift.checks';
import {
  analysisRow,
  DriftScenario,
  fact,
  failedCheck,
  JOB,
  passedCheck,
  readingScenario,
  STORED_READING,
  written,
  type Scenario,
} from './drift.scenario';

/* The Drift card in the seven states a reader meets it in: empty, running, re-running, result, new work,
   intent changed and paused. Each story is one state and asserts what the card holds in it: the heading and
   the one sentence before any analysis, the progress alone while it runs, the last result dimmed while it
   runs again, one verdict line and a quiet footer after it, and, from the first reading on, a re-run control in
   the card's header that stays there in every state, inert where a press cannot run. Pause model calls and the
   Live monitor sit behind one Drift settings control in the header, never in the card body. */

const meta = {
  title: 'Drift/Card states',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });
const WRITES = [
  written('w1', 220, 'src/queue/worker.ts'),
  written('w2', 240, 'src/queue/index.ts'),
];
const READ_FACTS = [PERSON, ...WRITES, failedCheck('c1', 500), passedCheck('c2', 600)];
const HIGH = { analysis_levels: [analysisRow('claude')] };

async function drawn(canvasElement: HTMLElement): Promise<HTMLElement> {
  return within(canvasElement).findByRole('region', { name: 'Drift' });
}

const head = (card: HTMLElement) => card.querySelector('header') as HTMLElement;

/* The re-run controls the card draws, by name: Analyze again over a current reading, Check again over one
   that new work or a changed intent left behind. */
const rerun = (root: HTMLElement) =>
  within(root).queryAllByRole('button', { name: /^(Analyze again|Check again)$/ });

async function readingDrawn(card: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const node = card.querySelector<HTMLElement>('[data-next-result]');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
}

const sentButtons = (card: HTMLElement) =>
  within(card).queryAllByRole('button', { name: /^What is sent/ });

/* Empty: a heading, one sentence and Analyze drift. The monitor, the pause and the counter are not in the
   body, nothing says "Not checked yet" over an empty four-step bar, and Steer back waits for a departure. */
export const Empty: Story = {
  ...scenario({ facts: [PERSON, failedCheck('c1', 500)] }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const analyze = await within(card).findByRole('button', { name: 'Analyze drift' });
    await expect(analyze).toBeVisible();
    await expect(within(head(card)).getByRole('heading', { name: 'Drift' })).toBeVisible();
    await expect(
      within(head(card)).getByText('How far the session has moved from the goal'),
    ).toBeVisible();
    await expect(within(card).queryByText('Not checked yet')).toBeNull();
    await expect(card.querySelector('.next-session-drift-meter')).toBeNull();
    await expect(card.querySelector('.next-session-drift-scale')).toBeNull();
    await expect(card).not.toHaveTextContent(/drift checks? requested/);
    await expect(within(card).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await expect(within(card).queryByRole('button', { name: /model calls$/ })).toBeNull();
    await expect(within(card).queryByRole('switch', { name: 'Live monitor' })).toBeNull();
    await expect(rerun(card)).toHaveLength(0);
    await expect(sentButtons(card)).toHaveLength(1);
    // The settings are one press away, in the header.
    await userEvent.click(within(head(card)).getByRole('button', { name: 'Drift settings' }));
    const monitor = await within(document.body).findByRole('switch', { name: 'Live monitor' });
    await expect(monitor).toHaveAccessibleDescription(LIVE_HINT);
    await waitFor(() =>
      expect(
        within(document.body).getByRole('button', { name: 'Pause model calls' }),
      ).toBeVisible(),
    );
    await expect(card.querySelector('[data-next-drift-body]')?.contains(monitor)).toBe(false);
  },
};

/* Running, with no reading yet: the progress is the card's state. No "Not checked yet", no empty bar and no
   counter standing at 0 beside it, and no re-run control, because there is no reading to run again. */
export const Running: Story = {
  ...scenario({ facts: READ_FACTS, payload: { reading_jobs: { 'claude:s1': JOB } } }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const box = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-analyzing]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(box).getByText(JOB_TITLE)).toBeVisible();
    await expect(within(card).getByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(within(card).queryByText('Not checked yet')).toBeNull();
    await expect(card.querySelector('.next-session-drift-meter')).toBeNull();
    await expect(card).not.toHaveTextContent(/drift checks? requested/);
    await expect(card.querySelector('[data-next-result]')).toBeNull();
    await expect(rerun(card)).toHaveLength(0);
    await expect(within(card).queryByRole('button', { name: 'Steer back' })).toBeNull();
  },
};

/* Running again: the last result stays in view, dimmed and out of reach, under the progress. The re-run
   control is in the header, inert while the analysis runs. */
export const ReRunning: Story = {
  ...scenario({
    session: STORED_READING,
    facts: READ_FACTS,
    work: HIGH,
    payload: { reading_jobs: { 'claude:s1': JOB } },
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const result = await readingDrawn(card);
    await expect(card.querySelector('[data-next-analyzing]')).not.toBeNull();
    await expect(within(card).getByText('Reading again')).toBeVisible();
    const dimmed = result.closest<HTMLElement>('[data-next-result-dimmed]');
    await expect(dimmed).not.toBeNull();
    await expect(dimmed).toHaveAttribute('aria-busy', 'true');
    await expect(dimmed).toHaveAttribute('inert');
    await expect(within(result).getByText(/It stopped running the tests\./)).toBeInTheDocument();
    const again = rerun(head(card));
    await expect(again).toHaveLength(1);
    await expect(again[0]).toHaveAttribute('aria-disabled', 'true');
    await expect(rerun(card)).toHaveLength(1);
  },
};

/* Result: one verdict line, then the departures, then Steer back, with a quiet footer. The result is said
   once; the work list, the delegated-work line and the count are not between the verdict and the footer; What
   is sent is in one place. */
export const Result: Story = {
  ...scenario({ session: STORED_READING, facts: READ_FACTS, work: HIGH }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const result = await readingDrawn(card);
    const verdict = card.querySelector('[data-next-drift-verdict]') as HTMLElement;
    await expect(verdict).toBeVisible();
    // The verdict is said once: no second heading restates it under the level.
    await expect(card.querySelector('[data-next-result-heading]')).toBeNull();
    await expect(within(card).queryByText(RESULT_DEPARTS)).toBeNull();
    await expect(within(result).getByText(/It stopped running the tests\./)).toBeVisible();
    // Present from the first reading, in the header, enabled.
    const again = rerun(head(card));
    await expect(again).toHaveLength(1);
    await expect(again[0]).toHaveAccessibleName('Analyze again');
    await expect(again[0]).not.toHaveAttribute('aria-disabled', 'true');
    await expect(rerun(card)).toHaveLength(1);
    await expect(within(card).getByRole('button', { name: 'Steer back' })).toBeVisible();
    await expect(card).not.toHaveTextContent('Delegated work');
    // Moved under What the analysis read, folded until it is opened.
    await expect(within(card).getByText('Where the work went')).not.toBeVisible();
    // A quiet footer: Mark as inaccurate and What the analysis read, then What is sent and the count, once.
    const footer = card.querySelector<HTMLElement>('[data-next-result-footer]') as HTMLElement;
    await expect(within(footer).getByRole('button', { name: 'Mark as inaccurate' })).toBeVisible();
    await expect(
      within(footer).getByRole('button', { name: 'What the analysis read' }),
    ).toBeVisible();
    await expect(sentButtons(card)).toHaveLength(1);
    await expect(footer.contains(sentButtons(card)[0] ?? null)).toBe(true);
    await expect(footer).toHaveTextContent('1 drift check requested');
    await expect(card.textContent?.match(/drift checks? requested/g)).toHaveLength(1);
    await neverDone(card);
  },
};

/* New work: the marker sits in the header beside the read time, with Check again. It is not a box between
   the level and the result, and it holds no counter and no What is sent of its own. */
export const NewWork: Story = {
  ...scenario({
    session: STORED_READING,
    facts: [
      ...READ_FACTS,
      passedCheck('c3', 1200),
      fact('m1', 1250, { type: 'agent_message', by: 'agent' }),
    ],
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const stale = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-result-stale="work"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(head(card).contains(stale)).toBe(true);
    await expect(stale).toHaveTextContent('New work since this analysis.');
    await expect(stale.closest('[data-slot="card"]')).not.toHaveAttribute(
      'data-variant',
      'reading-stale',
    );
    const again = rerun(card);
    await expect(again).toHaveLength(1);
    await expect(again[0]).toHaveAccessibleName('Check again');
    await expect(head(card).contains(again[0] ?? null)).toBe(true);
    await expect(stale).not.toHaveTextContent(/drift checks? requested/);
    await expect(sentButtons(card)).toHaveLength(1);
    await expect(
      within(card).getByRole('button', { name: 'What the analysis read' }),
    ).toBeInTheDocument();
  },
};

/* Intent changed: the same header marker, saying the words changed, with Check again. */
export const IntentChanged: Story = {
  ...scenario({
    session: { ...STORED_READING, annotation_revision: 4, annotation_revision_count: 2 },
    facts: READ_FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const stale = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-result-stale="intent"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(head(card).contains(stale)).toBe(true);
    await expect(stale).toHaveTextContent('Your intent changed after this analysis.');
    const again = rerun(card);
    await expect(again).toHaveLength(1);
    await expect(again[0]).toHaveAccessibleName('Check again');
    await expect(head(card).contains(again[0] ?? null)).toBe(true);
    await expect(sentButtons(card)).toHaveLength(1);
  },
};

/* Paused: Resume model calls is in the header, the result stays, and the re-run control is there, inert. */
export const Paused: Story = {
  ...scenario({
    session: STORED_READING,
    facts: READ_FACTS,
    work: HIGH,
    payload: { reading: { consent: false, off: true, reason: 'model-calls-paused' } },
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    await readingDrawn(card);
    await expect(
      within(head(card)).getByRole('button', { name: 'Resume model calls' }),
    ).toBeVisible();
    const again = rerun(head(card));
    await expect(again).toHaveLength(1);
    await expect(again[0]).toHaveAttribute('aria-disabled', 'true');
    await expect(rerun(card)).toHaveLength(1);
    await expect(
      within(card).getAllByText('Model calls are paused. Nothing is sent until you resume.')[0],
    ).toBeVisible();
  },
};

const NOTICE = {
  kind: 'reading',
  provider: 'claude',
  destination: 'first.example',
  content: 4,
  tool_output: 'tools.example',
  at: 1000,
};

/* A one-time notice is open while the analysis it came with runs, and is collapsed under What is sent on the
   result that follows, where it is one disclosure with the rest of what is sent. */
const noticed = readingScenario([NOTICE]);
export const NoticeCollapsesOnceRead: Story = {
  ...scenario({
    reading: noticed,
    session: STORED_READING,
    facts: READ_FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    await readingDrawn(card);
    await expect(card.querySelector('[data-next-reading-notice]')).toBeNull();
    await userEvent.click(rerun(card)[0] as HTMLElement);
    const open = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-reading-notice]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(open).toBeVisible();
    await expect(open).toHaveTextContent('Words go to: first.example');
    await noticed.finish?.();
    await waitFor(() => expect(card.querySelector('[data-next-analyzing]')).toBeNull());
    await readingDrawn(card);
    await expect(card.querySelector('[data-next-reading-notice]')).toBeNull();
    const sent = sentButtons(card);
    await expect(sent).toHaveLength(1);
    await userEvent.click(sent[0] as HTMLElement);
    const dialog = await within(document.body).findByRole('dialog');
    await waitFor(() => expect(dialog).toHaveTextContent('Words go to: first.example'));
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Pause model calls' })).toBeVisible(),
    );
    await expect(rerun(card)).toHaveLength(1);
  },
};
