import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import {
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
    await expect(drift.querySelector('[data-next-disowned]')).toBeNull();
    const mark = within(row).getByRole('button', { name: RESULT_NOT_ACCURATE });
    mark.scrollIntoView({ block: 'center' });
    const before = row.getBoundingClientRect().top;
    await userEvent.click(mark);
    // After: one message, at the top where the level was, with Undo and Analyze again beside it.
    await waitFor(() => expect(row).toHaveAttribute('data-next-result-mark', 'marked'));
    const notice = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-marked]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(notice).getByRole('status')).toHaveTextContent(RESULT_MARKED);
    // Said once: the foot no longer repeats it, and no second Undo stands there.
    await expect(row.textContent).not.toContain('Marked inaccurate');
    await expect(within(row).queryByRole('button', { name: RESULT_UNMARK })).toBeNull();
    await expect(drift.textContent?.split(RESULT_MARKED).length).toBe(2);
    const undo = within(notice).getByRole('button', { name: RESULT_UNMARK });
    await expect(within(notice).getByRole('button', { name: 'Analyze again' })).toBeVisible();
    // The level and Steer back left the column above; the foot stayed where the press was.
    await expect(Math.abs(row.getBoundingClientRect().top - before)).toBeLessThan(4);
    await expect(drift.querySelector('[data-next-drift-level]')).toBeNull();
    await expect(within(drift).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await userEvent.click(undo);
    await waitFor(() => expect(row).toHaveAttribute('data-next-result-mark', 'unmarked'));
    await waitFor(() => expect(drift.querySelector('[data-next-drift-level]')).not.toBeNull());
    await expect(drift.querySelector('[data-next-drift-marked]')).toBeNull();
    await expect(drift.querySelector('[data-next-disowned]')).toBeNull();
  },
};

/* A reading marked inaccurate keeps its verdicts on the card, drawn as disowned, so a later scan does not
   read them as standing; the card offers a way forward. */
export const MarkedInaccurate: Story = {
  ...scenario({
    ...RESULT,
    session: { ...RESULT.session, annotation_not_accurate: true },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const row = await foot(drift);
    await expect(row).toHaveAttribute('data-next-result-mark', 'marked');
    const notice = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-marked]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(notice).getByRole('status')).toHaveTextContent(RESULT_MARKED);
    await expect(within(notice).getByRole('button', { name: RESULT_UNMARK })).toBeVisible();
    await expect(within(notice).getByRole('button', { name: 'Analyze again' })).toBeVisible();
    // The verdicts stay readable and are set aside: dimmed, and under the one message.
    const disowned = drift.querySelector<HTMLElement>('[data-next-disowned]');
    await expect(disowned).not.toBeNull();
    await expect(disowned).toHaveTextContent('Departs from your intent');
    await expect(Number(getComputedStyle(disowned as HTMLElement).opacity)).toBeLessThan(0.8);
    // The old wording is gone.
    await expect(drift.textContent).not.toContain('Not accurate?');
    await expect(drift.textContent).not.toContain('Drift level hidden because you marked');
  },
};

/* The Live monitor is the reader's opt-in switch, and a live estimate must not take the marked reading's slot:
   with it on and a live level row published, the message, Undo and Analyze again still stand. */
export const MarkedInaccurateWithTheLiveMonitorOn: Story = {
  ...scenario({
    ...RESULT,
    session: { ...RESULT.session, annotation_not_accurate: true },
    work: {
      analysis_levels: [analysisRow('claude')],
      live_levels: [
        {
          harness: 'claude',
          sid: 's1',
          revision: 3,
          computed_at: 990,
          level: 'high',
          reasons: ['failed-check'],
          cites: ['c1'],
          rose_at: '',
          rose_from: '',
        },
      ],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const head = drift.querySelector('header') as HTMLElement;
    await userEvent.click(within(head).getByRole('button', { name: 'Drift settings' }));
    const monitor = await within(document.body).findByRole('switch', { name: 'Live monitor' });
    await userEvent.click(monitor);
    await waitFor(() => expect(monitor).toHaveAttribute('aria-checked', 'true'));
    const notice = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-marked]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(notice).getByRole('status')).toHaveTextContent(RESULT_MARKED);
    await expect(within(notice).getByRole('button', { name: RESULT_UNMARK })).toBeVisible();
    await expect(within(notice).getByRole('button', { name: 'Analyze again' })).toBeVisible();
    await expect(drift.querySelector('[data-next-disowned]')).not.toBeNull();
  },
};

/* The card asks nothing it keeps nowhere: an optional "what was wrong" choice was held in this tab, sent to
   no one and outlived the reading, so a marked reading offers the mark and its way back and forward only. */
export const MarkedInaccurateOffersNoChoiceItDoesNotKeep: Story = {
  ...scenario({
    ...RESULT,
    session: { ...RESULT.session, annotation_not_accurate: true },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const notice = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-marked]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(notice).getByRole('button', { name: RESULT_UNMARK })).toBeVisible();
    await expect(notice.querySelector('[data-next-marked-wrong]')).toBeNull();
    await expect(notice).not.toHaveTextContent(/what was wrong/i);
    await expect(within(notice).queryByRole('button', { pressed: true })).toBeNull();
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
    await expect(section('model')).toHaveTextContent(/^Modelclaude-sonnet-5-5$/);
    await expect(section('intent')).toHaveTextContent(/typed .+ ago/);
    await expect([...section('intent').querySelectorAll('li')].map((li) => li.textContent)).toEqual(
      ['Goal “Ship the queue”', 'Expected outcome “Tests pass”'],
    );
    const session = [...section('session').querySelectorAll('li')];
    await expect(session.map((li) => li.textContent)).toEqual([
      'Everything up to the session’s end.',
      'Read all 4 entries after your intent: 1 from you, 1 file write, 1 failed check, 1 passed check.',
      'The oldest is from about 13h ago.',
      'How many other commands ran beside the entries read was not recorded for this reading.',
      // The level's range and reason, moved here from between the meter and the answer (2026-10-20).
      'Entries read: [1] to [4].',
      'pytest -q failed 8m ago at [2]; no passing re-run recorded.',
    ]);
    // Each item is its own line, not one run of words.
    await expect(new Set(session.map((li) => li.getBoundingClientRect().top)).size).toBe(6);
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
      annotation_goal: 'x'.repeat(1000),
      annotation_goal_source: 'first-prompt',
      annotation_assessment: {
        ...READING,
        goal_source: 'first-prompt',
        goal_source_at: 100,
        coverage: { ...READING.coverage, goal_source: 'whole' },
        criteria: {
          ...READING.criteria,
          goal: { ...READING.criteria.goal, clause: 'x'.repeat(1000) },
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
      'Shown cut at 1,000 characters; the analysis read the whole prompt, up to 1,000 characters.',
    );
  },
};

const READ_SECTION_CUTOFF =
  'Read all 14 entries after your intent: 10 messages from the agent, 1 file write, 3 checks with no recorded result. All are from within the last hour. 7 other commands ran, 4 of them read-only, and Compass read only when they ran.';

async function openWhatItRead(canvasElement: HTMLElement): Promise<HTMLElement> {
  const drift = await card(canvasElement);
  await userEvent.click(await within(drift).findByRole('button', { name: READ_SUMMARY }));
  return waitFor(() => {
    const node = drift.querySelector<HTMLElement>('[data-next-read]');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
}

export const WhatTheAnalysisReadNamesTheCommandsItNeverSaw: Story = {
  ...scenario({
    ...RESULT,
    session: {
      ...RESULT.session,
      annotation_assessment: {
        ...READING,
        cutoff: READ_SECTION_CUTOFF,
        coverage: { ...READING.coverage, other_commands: 7, read_only_commands: 4 },
      },
    },
  }),
  play: async ({ canvasElement }) => {
    const read = await openWhatItRead(canvasElement);
    await expect(read).toHaveTextContent(
      '7 other commands ran, 4 of them read-only, and Compass read only when they ran.',
    );
    await expect(read).not.toHaveTextContent('was not recorded for this reading');
  },
};

export const WhatTheAnalysisReadSaysAnOlderReadingNeverCountedThem: Story = {
  ...scenario({
    ...RESULT,
    session: {
      ...RESULT.session,
      annotation_assessment: { ...READING, cutoff: 'Read all 14 entries after your intent.' },
    },
  }),
  play: async ({ canvasElement }) => {
    const read = await openWhatItRead(canvasElement);
    await expect(read).toHaveTextContent(
      'How many other commands ran beside the entries read was not recorded for this reading.',
    );
  },
};
