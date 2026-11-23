import { openSessionTechnicalTab } from './sessionTechnical';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { clock } from '../src/observed';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  fact,
  failedCheck,
  passedCheck,
  readingScenario,
  type Scenario,
} from './drift.scenario';

/* A level above On track stands on a departure the reading shows. Evidence accounts for departures that
   clear and why a check could not place the work on the scale. */

const meta = {
  title: 'Drift/A level needs a departure',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });
const PASSED = passedCheck('c2', 600);
const FAILED = fact('c1', 500, {
  subject: 'check',
  result: 'failed',
  result_source: 'failed flag',
  summary: 'pytest -q',
});
const AGENT = fact('m5', 650, {
  type: 'agent_message',
  by: 'agent',
  summary: 'Done: the billing rate is now 0.25 in src/billing/invoice.ts.',
});

const READ = (criteria: Record<string, unknown>, scope = 'last-turn') => ({
  annotation_assessment: { ...DEPARTURE_READING, scope, criteria },
  annotation_reading_count: 1,
});
const CONSISTENT = {
  result: 'consistent with the evidence read',
  cites: ['c2'],
  detail: '',
  clause: 'Tests pass',
};
const CANT_TELL = {
  result: 'not verifiable from available evidence',
  cites: [],
  detail: '',
  clause: 'Tests pass',
};
const DEPARTS = {
  result: 'departure',
  cites: ['c1'],
  detail: 'It stopped running the tests.',
  clause: 'Ship the queue',
};
const LIVE_MEDIUM = {
  harness: 'claude',
  sid: 's1',
  level: 'medium',
  revision: 3,
  computed_at: 990,
  reasons: ['pass-then-write'],
  cites: ['c2'],
  rose_at: '',
  rose_from: '',
};

async function evidencePanel(canvasElement: HTMLElement): Promise<HTMLElement> {
  await openSessionTechnicalTab('Evidence', canvasElement);
  const panel = within(canvasElement).getByRole('tabpanel', { name: 'Evidence' });
  await waitFor(() => expect(panel.querySelector('[data-next-result]')).not.toBeNull());
  return panel;
}

const verdictOf = (drift: HTMLElement) =>
  waitFor(() => {
    const node = drift.querySelector<HTMLElement>('[data-next-drift-verdict]');
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });

/* Every line Can't tell and no departure: the level rows say Medium (a failed check, a live estimate), and
   neither the card nor the header may. The live monitor is switched on, so its estimate has every chance to
   stand in. */
export const CantTellOnEveryLineDrawsNoLevel: Story = {
  ...scenario({
    session: READ({
      goal: { ...CANT_TELL, clause: 'Ship the queue' },
      line_1: CANT_TELL,
    }),
    facts: [PERSON, FAILED, PASSED, AGENT],
    work: {
      analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['failed-check'] }],
      live_levels: [LIVE_MEDIUM],
    },
  }),
  play: async ({ canvasElement }) => {
    const progress = await within(canvasElement).findByRole('region', { name: 'Is it on track?' });
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    const monitor = await privacy.findByRole('switch', { name: 'Live monitor' });
    await userEvent.click(monitor);
    await waitFor(() => expect(monitor).toHaveAttribute('aria-checked', 'true'));
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    const verdict = await evidence.findByText(/^A check failed at /);
    await expect(verdict.textContent).not.toMatch(/Medium|High|Extreme/);
    await expect(
      await within(progress).findByText(/^(Can't tell|Too early to tell)$/),
    ).toBeVisible();
    await expect(progress.querySelector('.next-session-drift-meter')).toBeNull();
    await expect(progress.querySelector('[data-next-drift-pill]')).toBeNull();
    // The switch is on and the estimate has a level, so the reader is told why it is not drawn.
    await expect(
      await evidence.findByText(
        'The live estimate is not drawn while this reading stands: it reads checks and file paths, never your intent.',
      ),
    ).toBeVisible();
  },
};

/* Every line Consistent and the level held back: the one sentence says why, and the disclosure that asked
   "why not None or low" over a level that was never drawn is gone. */
export const ConsistentButHeldBackSaysWhyInTheSentence: Story = {
  ...scenario({
    session: READ({
      goal: { ...CONSISTENT, clause: 'Ship the queue' },
      line_1: CONSISTENT,
    }),
    facts: [PERSON, PASSED, AGENT],
    work: {
      analysis_levels: [
        {
          ...analysisRow('claude', 'not_enough'),
          reasons: ['line-not-shown-by-a-check'],
          cites: ['c2'],
        },
      ],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await evidencePanel(canvasElement);
    const verdict = await verdictOf(drift);
    await expect(verdict).toHaveTextContent(
      'Nothing found against what it read, but no level is drawn: a line of your intent is not shown by any check.',
    );
    await expect(drift.textContent).not.toContain('Why not None or low');
    await expect(drift.querySelector('[data-next-drift-level]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
  },
};

/* A goal alone, nothing departing and no check showing it done: the sentence says so and says what would let a
   level be drawn (owner decision, 2026-10-23: the evidence floor stands). */
export const GoalOnlyHeldBackNamesTheCheckItNeeds: Story = {
  ...scenario({
    session: {
      ...READ({ goal: { ...CONSISTENT, clause: 'Ship the queue' } }),
      annotation_line_1: '',
    },
    facts: [PERSON, PASSED, AGENT],
    work: {
      analysis_levels: [
        {
          ...analysisRow('claude', 'not_enough'),
          reasons: ['line-not-shown-by-a-check'],
          cites: ['c2'],
        },
      ],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await evidencePanel(canvasElement);
    await expect(await verdictOf(drift)).toHaveTextContent(
      'Nothing departs from your goal, but no check shows it done, so no level is drawn. Run a check that shows the goal is done (a test, lint or build), then analyze again.',
    );
    await expect(drift.querySelector('[data-next-drift-level]')).toBeNull();
  },
};

/* A Medium the server read from a contradicted claim, with nothing departing: no level, and the sentence says
   what the reading did find. */
export const AContradictedClaimAloneDrawsNoMedium: Story = {
  ...scenario({
    session: READ({
      goal: { ...CONSISTENT, clause: 'Ship the queue' },
      line_1: CONSISTENT,
    }),
    facts: [PERSON, PASSED, AGENT],
    work: {
      analysis_levels: [
        { ...analysisRow('claude', 'medium'), reasons: ['claim-contradicted'], cites: ['m5'] },
      ],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await evidencePanel(canvasElement);
    const verdict = await verdictOf(drift);
    await expect(verdict).toHaveTextContent(
      /^Nothing found against what it read, but no level is drawn: the record contradicts what the agent said\./,
    );
    await expect(drift.textContent).not.toMatch(/\bMedium\b/);
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
  },
};

/* A reading that found a departure shows its plain level while the session works and keeps its supporting
   evidence one click away. */
export const ADepartureKeepsItsLevelWhileTheSessionWorks: Story = {
  ...scenario({
    session: READ({ goal: DEPARTS, line_1: CANT_TELL }),
    facts: [PERSON, FAILED, PASSED, AGENT],
    work: {
      analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }],
    },
  }),
  play: async ({ canvasElement }) => {
    const progress = await within(canvasElement).findByRole('region', { name: 'Is it on track?' });
    await waitFor(() =>
      expect(progress.querySelector('[data-next-drift-pill]')).toHaveTextContent(
        'Slightly off course',
      ),
    );
    await expect(within(progress).getByText(/^Checked .* against your goal$/)).toBeVisible();
    const drift = await evidencePanel(canvasElement);
    const verdict = await verdictOf(drift);
    await expect(verdict).toHaveTextContent(/^Medium: 1 departure/);
    await expect(within(drift).getByText(/^From the progress check at/)).toBeVisible();
  },
};

export const AStoredCodexDepartureKeepsItsReadingWithoutALevel: Story = {
  ...scenario({
    harness: 'codex',
    session: { ...READ({ goal: DEPARTS }), annotation_line_1: '' },
    facts: [
      fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' }, 'codex'),
      failedCheck('c1', 500, 'codex'),
    ],
    work: { analysis_levels: [analysisRow('codex', 'medium')] },
  }),
  play: async ({ canvasElement }) => {
    const drift = await evidencePanel(canvasElement);
    await expect(within(drift).getByText(DEPARTS.detail)).toBeVisible();
    await expect(drift.querySelector('[data-next-drift-level]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
    await expect(drift).not.toHaveTextContent('From the progress check at');
  },
};

/* The next reading finds no departure where the one before found one: the card names the cleared departure
   once, with the time of the reading it came from, and the reading after that does not repeat it. The
   board is advanced by finishing a press, which refreshes it over the session object mutated here. */
const CLEARING_SESSION: Record<string, unknown> = {
  ...READ({ goal: DEPARTS, line_1: CANT_TELL }),
  state: 'idle',
};
const CLEARING = readingScenario([null, null]);
const readAt = (at: number, criteria: Record<string, unknown>) => ({
  ...DEPARTURE_READING,
  read_at: at,
  evidence_through: at,
  criteria,
});
export const AClearedDepartureIsNamedOnceOnTheNextReading: Story = {
  ...scenario({
    session: CLEARING_SESSION,
    facts: [PERSON, FAILED, PASSED, AGENT],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: CLEARING,
  }),
  play: async ({ canvasElement }) => {
    await evidencePanel(canvasElement);
    await expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull();
    // The next reading clears it: nothing departs now, and the session has gone idle.
    CLEARING_SESSION['annotation_assessment'] = readAt(1100, {
      goal: { ...CANT_TELL, clause: 'Ship the queue' },
      line_1: CANT_TELL,
    });
    await CLEARING.finish?.();
    const cleared = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-cleared]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(cleared).toHaveTextContent(
      `The departure from the ${clock(1000)} reading no longer holds.`,
    );
    await expect(canvasElement.querySelectorAll('[data-next-drift-cleared]')).toHaveLength(1);
    // A reading after that one says nothing about it.
    CLEARING_SESSION['annotation_assessment'] = readAt(1200, {
      goal: { ...CANT_TELL, clause: 'Ship the queue' },
      line_1: CANT_TELL,
    });
    await CLEARING.finish?.();
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull(),
    );
  },
};

/* Two departures, then one: the next reading no longer finds the line's, and the card says one went while the
   other stands. A clear to zero was the only case named before; a reader watching "2 departures" become
   "1 departure" had no word that the other had been met. */
const PARTIAL_SESSION: Record<string, unknown> = {
  ...READ({
    goal: DEPARTS,
    line_1: { ...DEPARTS, detail: 'It never ran the lint.', clause: 'Tests pass' },
  }),
  state: 'idle',
};
const PARTIAL = readingScenario([null]);
export const APartialClearIsNamedOnTheNextReading: Story = {
  ...scenario({
    session: PARTIAL_SESSION,
    facts: [PERSON, FAILED, PASSED, AGENT],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: PARTIAL,
  }),
  play: async ({ canvasElement }) => {
    const drift = await evidencePanel(canvasElement);
    await expect(await verdictOf(drift)).toHaveTextContent(/2 departures/);
    await expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull();
    PARTIAL_SESSION['annotation_assessment'] = readAt(1100, {
      goal: DEPARTS,
      line_1: CANT_TELL,
    });
    await PARTIAL.finish?.();
    const cleared = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-cleared]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(cleared).toHaveTextContent(
      `The departure from the ${clock(1000)} reading no longer holds.`,
    );
    await expect(await verdictOf(drift)).toHaveTextContent(/1 departure\b/);
  },
};

/* A reading of a session a few minutes old that could tell nothing: it says it is early, so the empty verdict
   reads as too soon to say. */
export const AnEmptyVerdictEarlyInASessionSaysItIsEarly: Story = {
  ...scenario({
    session: {
      annotation_assessment: {
        ...DEPARTURE_READING,
        scope: 'mid-flight',
        evidence_through: 700,
        criteria: {
          goal: { ...CANT_TELL, clause: 'Ship the queue' },
          line_1: CANT_TELL,
        },
      },
      annotation_reading_count: 1,
    },
    facts: [PERSON, PASSED],
    work: { analysis_levels: [{ ...analysisRow('claude', 'not_enough'), reasons: [] }] },
  }),
  play: async ({ canvasElement }) => {
    const drift = await evidencePanel(canvasElement);
    await expect(await verdictOf(drift)).toHaveTextContent("Can't tell from what was read.");
    await waitFor(() =>
      expect(drift.querySelector('[data-next-drift-early]')).toHaveTextContent(
        'Early: this reading covers only the first 8m of the session. Read again once it has run its checks.',
      ),
    );
  },
};

function absenceStory(
  value: Scenario,
  label: string,
  reason: RegExp,
  check = 'Check progress again',
): Story {
  return {
    ...scenario(value),
    play: async ({ canvasElement }) => {
      const view = within(canvasElement);
      const progress = await view.findByRole('region', { name: 'Is it on track?' });
      const card = within(progress);
      const word = await card.findByText(label, { exact: true });
      const absence = word.closest('[data-next-progress-absence]');
      await expect(absence).not.toBeNull();
      await expect(within(absence as HTMLElement).getByText('How this works')).toBeVisible();
      await expect(absence).toHaveTextContent(reason);
      await expect(absence?.querySelector('svg')).toBeNull();
      await expect(progress.querySelector('[data-next-drift-pill]')).toBeNull();
      await expect(progress.querySelector('.next-session-drift-meter')).toBeNull();
      await expect(card.queryByText('On track')).toBeNull();
      const button = card.getByRole('button', { name: check });
      await expect(button.querySelector('svg[data-icon="check-progress"]')).not.toBeNull();
      await expect(card.getByText(/^Uses AI/)).toBeVisible();
      await expect(progress.textContent).not.toMatch(/\b(?:drift|analyze)\b/i);
    },
  };
}

export const NoGoalYet = absenceStory(
  {
    unsaved: true,
    session: { first_prompt: '', first_prompt_at: null, latest_prompt: '', latest_prompt_at: null },
  },
  'No goal yet',
  /Give Compass a goal/,
  'Check progress',
);

export const NotCheckedYet = absenceStory(
  {},
  'Not checked yet',
  /no saved progress check/,
  'Check progress',
);

export const TooEarlyToTell = absenceStory(
  {
    session: READ({ goal: CANT_TELL, line_1: CANT_TELL }),
    facts: [fact('u-short', 850, { type: 'user_message', by: 'person:me' })],
  },
  'Too early to tell',
  /first 2 minutes/,
);

export const CantTell = absenceStory(
  {
    session: READ({ goal: { ...CANT_TELL, clause: 'Ship the queue' }, line_1: CANT_TELL }),
    facts: [PERSON, AGENT],
  },
  "Can't tell",
  /enough evidence/,
);

export const GoalTooVagueToCheck = absenceStory(
  {
    session: READ({
      goal: {
        result: 'goal too vague to analyze against',
        cites: [],
        detail: '',
        clause: 'Improve it',
      },
    }),
  },
  'Goal too vague to check',
  /specific outcome/,
);

export const OutOfDate = absenceStory(
  {
    session: { ...READ({ goal: DEPARTS }), annotation_revision: 4 },
    facts: [FAILED],
  },
  'Out of date',
  /earlier work or an earlier goal/,
);
