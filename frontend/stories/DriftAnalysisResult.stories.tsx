import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import {
  LEVEL_HIDDEN_MARKED,
  READ_NEVER,
  READ_SUMMARY,
  RESULT_MARKED,
  RESULT_NOT_ACCURATE,
  RESULT_NOT_ACCURATE_HINT,
  RESULT_UNMARK,
} from '../src/drift/sentences';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  failedCheck,
  fact,
  passedCheck,
  STORED_READING,
  written,
  type Scenario,
} from './drift.scenario';

/* The parts of a stored analysis a reader tunes most: the spent-budget banner, the Mark as inaccurate control
   and what it changes, and the What the analysis read panel. Each story mounts the real session page over a
   scripted backend, so the design can be iterated here and the play functions keep the behaviour honest.
   Parts with no role or name are found by the `data-` hook the page draws on them, never by a class. */

const meta = {
  title: 'Drift/Analysis result: limit, inaccurate mark, what it read',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

/* The person's message comes after the failed check, so Steer back is offered by the analysis's departure
   alone and a mark is seen to withdraw it. A failed check after the person's last message would offer Steer
   back on its own, mark or no mark. */
const RECORD = [
  written('w1', 220, 'src/queue/worker.ts'),
  failedCheck('c1', 500),
  fact('u1', 550, { type: 'user_message', by: 'person:me', summary: 'Ship it' }),
  passedCheck('c2', 600),
];

/* The reading as the producer now words it: a final scope, the model's stamp and the cutoff's sentences. */
const READING = {
  ...DEPARTURE_READING,
  scope: 'final',
  stamp: 'claude-sonnet-5-5 · read at 09:38',
  cutoff:
    'Read all 4 entries after your intent: 1 from you, 1 file write, 1 failed check, 1 passed check. The oldest is from about 13h ago.',
};

const RESULT: Scenario = {
  session: { ...STORED_READING, annotation_assessment: READING },
  facts: RECORD,
  work: { analysis_levels: [analysisRow('claude')] },
};

async function card(canvasElement: HTMLElement): Promise<HTMLElement> {
  return within(canvasElement).findByRole('region', { name: 'Drift' });
}

/* The foot is the Mark as inaccurate row; `data-next-result-mark` names its state. */
async function foot(root: HTMLElement): Promise<HTMLElement> {
  return waitFor(() => {
    const node = root.querySelector<HTMLElement>('[data-next-result-mark]');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
}

async function noBudgetLine(root: HTMLElement) {
  await expect(root.textContent).not.toMatch(/left today/);
  await expect(root.textContent).not.toMatch(/of \d+ left/);
}

export const UnderTheLimitSaysNothingAboutIt: Story = {
  ...scenario(RESULT),
  play: async ({ canvasElement }) => {
    await foot(await card(canvasElement));
    await noBudgetLine(canvasElement);
    await expect(canvasElement.querySelector('[data-next-reading-cap]')).toBeNull();
  },
};

/* Paused with a current result: the re-run control stays in the head, inert, and Resume model calls stays
   drawn beside it, outside any popover, because it changes permission and starts nothing. */
export const PausedResultStillOffersResume: Story = {
  ...scenario({
    ...RESULT,
    payload: { reading: { consent: false, off: true, reason: 'model-calls-paused' } },
  }),
  play: async ({ canvasElement }) => {
    const root = await card(canvasElement);
    await foot(root);
    const resume = await within(root).findByRole('button', { name: 'Resume model calls' });
    await expect(resume).toBeVisible();
    await expect(within(root).getAllByRole('button', { name: 'Resume model calls' })).toHaveLength(
      1,
    );
    await expect(within(root).getByRole('button', { name: 'Analyze again' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  },
};

export const LimitReachedHoldsTheTopOfThePage: Story = {
  ...scenario({
    ...RESULT,
    payload: {
      reading: {
        providers: { claude: true, codex: true },
        words: { claude: true, codex: true },
        tool_output: { claude: ['api'] },
        used: 100,
        limit: 100,
        reason: 'daily-cap',
        retry_at: Math.floor(Date.now() / 1000) + 3600,
      },
    },
  }),
  play: async ({ canvasElement }) => {
    const banner = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-reading-cap]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(banner).toHaveAttribute('role', 'status');
    await expect(banner).toHaveTextContent(
      /^You’ve reached the limit of 100 drift analyses for the past 24 hours\. You can analyze again at .+\.$/,
    );
    // The top 2rem of the viewport, and still there once the page has scrolled.
    const rem = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
    await expect(banner.getBoundingClientRect().height).toBeGreaterThanOrEqual(2 * rem - 1);
    await expect(getComputedStyle(banner).position).toBe('sticky');
    window.scrollTo(0, document.documentElement.scrollHeight);
    await waitFor(() => expect(Math.round(banner.getBoundingClientRect().top)).toBe(0));
    window.scrollTo(0, 0);
    await noBudgetLine(canvasElement);
  },
};

export const MarkAsInaccurateSaysWhatItDoes: Story = {
  ...scenario({ ...RESULT, keepsMarks: true }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const row = await foot(drift);
    await expect(row).toHaveAttribute('data-next-result-mark', 'unmarked');
    // Before the press: what it does, beside the control.
    await expect(row).toHaveTextContent(RESULT_NOT_ACCURATE_HINT);
    await waitFor(() => expect(drift.querySelector('[data-next-drift-level]')).not.toBeNull());
    await within(drift).findByRole('button', { name: 'Steer back' });
    const mark = within(row).getByRole('button', { name: RESULT_NOT_ACCURATE });
    mark.scrollIntoView({ block: 'center' });
    const before = row.getBoundingClientRect().top;
    await userEvent.click(mark);
    // After: what changed, said beside the control, and Undo in its place.
    await waitFor(() => expect(row).toHaveAttribute('data-next-result-mark', 'marked'));
    await expect(within(row).getByRole('status')).toHaveTextContent(RESULT_MARKED);
    const undo = within(row).getByRole('button', { name: RESULT_UNMARK });
    // The level and Steer back left the column above; the control stayed where it was pressed.
    await expect(Math.abs(row.getBoundingClientRect().top - before)).toBeLessThan(4);
    await expect(drift.querySelector('[data-next-drift-level]')).toBeNull();
    await expect(drift.querySelector('[data-next-drift-marked]')).toHaveTextContent(
      LEVEL_HIDDEN_MARKED,
    );
    await expect(within(drift).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await userEvent.click(undo);
    await waitFor(() => expect(row).toHaveAttribute('data-next-result-mark', 'unmarked'));
    await waitFor(() => expect(drift.querySelector('[data-next-drift-level]')).not.toBeNull());
    await expect(drift.querySelector('[data-next-drift-marked]')).toBeNull();
  },
};

export const MarkedInaccurate: Story = {
  ...scenario({
    ...RESULT,
    session: { ...RESULT.session, annotation_not_accurate: true },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const row = await foot(drift);
    await expect(row).toHaveAttribute('data-next-result-mark', 'marked');
    await expect(within(row).getByRole('status')).toHaveTextContent(RESULT_MARKED);
    await expect(within(row).getByRole('button', { name: RESULT_UNMARK })).toBeVisible();
    await expect(drift.querySelector('[data-next-drift-marked]')).toHaveTextContent(
      LEVEL_HIDDEN_MARKED,
    );
    // The old wording is gone.
    await expect(drift.textContent).not.toContain('Not accurate?');
    await expect(drift.textContent).not.toContain('You marked this analysis not accurate.');
  },
};

export const WhatTheAnalysisRead: Story = {
  ...scenario(RESULT),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const summary = await within(drift).findByRole('button', { name: READ_SUMMARY });
    await userEvent.click(summary);
    const read = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-read]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    const section = (name: string) =>
      read.querySelector<HTMLElement>(`[data-next-read-section="${name}"]`) as HTMLElement;
    const headings = [...read.querySelectorAll('h4')].map((h) => h.textContent);
    await expect(headings).toEqual([
      'Model',
      'Your intent',
      'The session',
      'Where the work went',
      'Not read',
    ]);
    await expect(section('model')).toHaveTextContent('claude-sonnet-5-5 · read at 09:38');
    await expect(section('intent')).toHaveTextContent(/typed .+ ago/);
    await expect([...section('intent').querySelectorAll('li')].map((li) => li.textContent)).toEqual(
      ['Goal “Ship the queue”', 'Expected outcome “Tests pass”'],
    );
    const session = [...section('session').querySelectorAll('li')];
    await expect(session.map((li) => li.textContent)).toEqual([
      'Everything up to the session’s end.',
      'Read all 4 entries after your intent: 1 from you, 1 file write, 1 failed check, 1 passed check.',
      'The oldest is from about 13h ago.',
      // The level's range and reason, moved here from between the meter and the answer (2026-10-20).
      'Entries read: [1] to [4].',
      'pytest -q failed 8m ago at [2]; no passing re-run recorded.',
    ]);
    // Each item is its own line, not one run of words.
    await expect(new Set(session.map((li) => li.getBoundingClientRect().top)).size).toBe(5);
    await expect(section('not-read')).toHaveTextContent(READ_NEVER);
    for (const retired of [
      'A reading is one model pass',
      'What it reads is the evidence on this page',
      'Baseline from your prompt',
      'GOAL FROM YOUR PROMPT',
      'Revision 3',
    ]) {
      await expect(read.textContent).not.toContain(retired);
    }
  },
};

export const WhatTheAnalysisReadFromAPromptGoal: Story = {
  ...scenario({
    ...RESULT,
    session: {
      ...RESULT.session,
      annotation_goal: 'x'.repeat(240),
      annotation_goal_source: 'first-prompt',
      annotation_assessment: {
        ...READING,
        goal_source: 'first-prompt',
        goal_source_at: 100,
        coverage: { ...READING.coverage, goal_source: 'whole' },
        criteria: {
          ...READING.criteria,
          goal: { ...READING.criteria.goal, clause: 'x'.repeat(240) },
        },
      },
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    await userEvent.click(await within(drift).findByRole('button', { name: READ_SUMMARY }));
    const intent = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-read-section="intent"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(intent).toHaveTextContent(/drafted from your prompt/);
    await expect(intent).toHaveTextContent(
      'Shown cut at 240 characters; the analysis read the whole prompt, up to 1,000 characters.',
    );
  },
};
