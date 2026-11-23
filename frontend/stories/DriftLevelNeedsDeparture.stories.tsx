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
  leaseScenario,
  leaseState,
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
    await expect(canvasElement.querySelector('.next-session-detail-header')).toHaveTextContent(
      'Slightly off course so far',
    );
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

const ABSENCE_WORDS = [
  'No goal yet',
  'Not checked yet',
  'Too early to tell',
  "Can't tell",
  'Goal too vague to check',
  'Out of date',
];

async function progressCard(canvasElement: HTMLElement) {
  return within(canvasElement).findByRole('region', { name: 'Is it on track?' });
}

async function expectNoLevel(progress: HTMLElement) {
  await expect(
    progress.querySelector('[data-next-drift-pill], .next-session-drift-meter'),
  ).toBeNull();
}

async function expectAbsence(progress: HTMLElement, label: string, reason: RegExp) {
  const card = within(progress);
  const word = await card.findByText(label, { exact: true });
  const absence = word.closest('[data-next-progress-absence]') as HTMLElement;
  await expect(absence).not.toBeNull();
  await expect(within(absence).getByText('How this works')).toBeVisible();
  await expect(absence).toHaveTextContent(reason);
  await expect(absence.querySelector('svg')).toBeNull();
  for (const other of ABSENCE_WORDS.filter((value) => value !== label)) {
    await expect(card.queryByText(other, { exact: true })).toBeNull();
  }
  await expect(card.queryByText('On track', { exact: true })).toBeNull();
  await expectNoLevel(progress);
}

function absenceStory(
  name: string,
  value: Scenario,
  label: string,
  reason: RegExp,
  check = 'Check progress again',
): Story {
  return {
    name,
    ...scenario(value),
    play: async ({ canvasElement }) => {
      const progress = await progressCard(canvasElement);
      await expectAbsence(progress, label, reason);
      const card = within(progress);
      const button = card.getByRole('button', { name: check });
      await expect(button.querySelector('svg[data-icon="check-progress"]')).not.toBeNull();
      await expect(card.getByText(/^Uses AI/)).toBeVisible();
      await expect(progress.textContent).not.toMatch(/\b(?:drift|analyze)\b/i);
    },
  };
}

function currentLevelStory(
  name: string,
  level: string,
  word: string,
  session: Record<string, unknown>,
  facts: readonly unknown[],
): Story {
  return {
    name,
    ...scenario({ session, facts, work: { analysis_levels: [analysisRow('claude', level)] } }),
    play: async ({ canvasElement }) => {
      const progress = await progressCard(canvasElement);
      const card = within(progress);
      const pill = await waitFor(() => {
        const node = progress.querySelector('[data-next-drift-pill]');
        expect(node).not.toBeNull();
        return node;
      });
      await expect(pill?.textContent).toBe(word);
      await expect(progress.querySelectorAll('[data-next-drift-pill]')).toHaveLength(1);
      await expect(
        progress.querySelector('.next-session-drift-scale [data-current]'),
      ).toHaveTextContent(word);
      await expect(progress.querySelectorAll('.next-session-drift-meter > span')).toHaveLength(4);
      for (const absent of ABSENCE_WORDS) {
        await expect(card.queryByText(absent, { exact: true })).toBeNull();
      }
      await expect(card.getByText(/^Checked .* against your goal$/)).toBeVisible();
      const header = canvasElement.querySelector('.next-session-detail-header');
      await expect(header).toHaveTextContent(word);
      if (level === 'none_or_low') {
        await expect(card.getByText('No departure found in what Compass read')).toBeVisible();
        await expect(card.queryByText('Where it went off course')).toBeNull();
      } else {
        await expect(card.getByText(/^Compass found 1 departure/)).toBeVisible();
        await expect(card.queryByText('No departure found in what Compass read')).toBeNull();
      }
    },
  };
}

const CURRENT_DEPARTURE = { ...READ({ goal: DEPARTS }), state: 'idle' };

export const Progress01OnTrack = currentLevelStory(
  '01 · On track',
  'none_or_low',
  'On track',
  {
    ...READ({ goal: { ...CONSISTENT, clause: 'Ship the queue' }, line_1: CONSISTENT }),
    state: 'idle',
  },
  [PERSON, PASSED],
);

export const Progress02SlightlyOffCourse = currentLevelStory(
  '02 · Slightly off course',
  'medium',
  'Slightly off course',
  CURRENT_DEPARTURE,
  [PERSON, FAILED],
);

export const Progress03OffCourse = currentLevelStory(
  '03 · Off course',
  'high',
  'Off course',
  CURRENT_DEPARTURE,
  [PERSON, FAILED],
);

export const Progress04WayOffCourse = currentLevelStory(
  '04 · Way off course',
  'extreme',
  'Way off course',
  CURRENT_DEPARTURE,
  [PERSON, FAILED],
);

export const Progress05NoGoalYet = absenceStory(
  '05 · No goal yet',
  {
    unsaved: true,
    session: { annotation_goal: '', annotation_goal_why: 'No goal typed for this session.' },
  },
  'No goal yet',
  /Give Compass a goal/,
  'Check progress',
);

export const Progress06NotCheckedYet = absenceStory(
  '06 · Not checked yet',
  {},
  'Not checked yet',
  /no saved progress check/,
  'Check progress',
);

export const Progress07TooEarlyToTell = absenceStory(
  '07 · Too early to tell',
  {
    session: READ({ goal: CANT_TELL, line_1: CANT_TELL }),
    facts: [fact('u-short', 850, { type: 'user_message', by: 'person:me' })],
  },
  'Too early to tell',
  /first 2 minutes/,
);

export const Progress08CantTell = absenceStory(
  "08 · Can't tell",
  {
    session: READ({ goal: { ...CANT_TELL, clause: 'Ship the queue' }, line_1: CANT_TELL }),
    facts: [PERSON, AGENT],
  },
  "Can't tell",
  /enough evidence/,
);

export const Progress09GoalTooVagueToCheck = absenceStory(
  '09 · Goal too vague to check',
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

export const Progress10OutOfDate = absenceStory(
  '10 · Out of date',
  {
    session: { ...READ({ goal: DEPARTS }), annotation_revision: 4 },
    facts: [FAILED],
  },
  'Out of date',
  /earlier work or an earlier goal/,
);

export const Progress11Withdrawn: Story = {
  name: '11 · Withdrawn',
  ...scenario({
    session: READ({ goal: DEPARTS }, 'withdrawn'),
    facts: [PERSON, FAILED],
    work: { analysis_levels: [analysisRow('claude', 'medium')] },
  }),
  play: async ({ canvasElement }) => {
    const progress = await progressCard(canvasElement);
    const card = within(progress);
    await expectAbsence(progress, 'Out of date', /This check was withdrawn/);
    await expect(card.queryByText(/^Checked .* against your goal$/)).toBeNull();
    await expect(card.queryByText('What the earlier check found')).toBeNull();
    await expect(card.queryByRole('button', { name: 'Steer back' })).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-progress]')).toBeNull();
    await expect(card.getByRole('button', { name: 'Check progress again' })).toBeVisible();
  },
};

export const Progress12CodexDeparture: Story = {
  name: '12 · Codex departure',
  ...scenario({
    harness: 'codex',
    session: { ...READ({ goal: DEPARTS }), annotation_line_1: '' },
    facts: [failedCheck('c1', 500, 'codex')],
    work: { analysis_levels: [analysisRow('codex', 'medium')] },
  }),
  play: async ({ canvasElement }) => {
    const progress = await progressCard(canvasElement);
    const card = within(progress);
    await expect(await card.findByText(/^Compass found 1 departure/)).toBeVisible();
    await expectNoLevel(progress);
    await expect(progress.querySelector('[data-next-progress-absence]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-progress]')).toBeNull();
    await expect(card.queryByRole('button', { name: 'Steer back' })).toBeNull();
  },
};

export const Progress13NewerCheckFailed: Story = {
  name: '13 · A newer check failed',
  ...scenario({
    session: {
      ...READ({ goal: DEPARTS }),
      annotation_reading_withheld: 'The progress check failed. No new reading was saved.',
      annotation_reading_withheld_at: 1050,
    },
    facts: [PERSON, FAILED],
    work: { analysis_levels: [analysisRow('claude', 'medium')] },
  }),
  play: async ({ canvasElement }) => {
    const progress = await progressCard(canvasElement);
    const card = within(progress);
    await expectAbsence(
      progress,
      "Can't tell",
      /The latest progress check did not produce a reading/,
    );
    await expect(card.getByText(/The progress check failed/)).toBeVisible();
    await expect(card.getByText('What the earlier check found')).toBeVisible();
    await expect(card.queryByText('Where it went off course')).toBeNull();
    await expect(card.queryByText(/^Checked .* against your goal$/)).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-progress]')).toBeNull();
    await expect(card.getByRole('button', { name: 'Check progress again' })).toBeVisible();
  },
};

const MONITOR_ABSTAINED = {
  level: 'not_enough',
  model_level: 'not_enough',
  floor_applied: false,
  reason: 'Too little work was recorded.',
  cites: [],
  fallback: 'not_enough',
  source: 'Live monitor · Haiku',
  checked_at: 1090,
};

function monitorStory(name: string, run: boolean): Story {
  return {
    name,
    ...scenario({ lease: leaseScenario(leaseState({ level: run ? MONITOR_ABSTAINED : null })) }),
    play: async ({ canvasElement }) => {
      const progress = await progressCard(canvasElement);
      const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
      const monitor = await privacy.findByRole('switch', { name: 'Live monitor' });
      await userEvent.click(monitor);
      await waitFor(() => expect(monitor).toBeChecked());
      if (run) {
        await expectAbsence(
          progress,
          'Too early to tell',
          /The Live monitor had too little recorded work/,
        );
      } else {
        await expectAbsence(
          progress,
          'Not checked yet',
          /The Live monitor has not completed a check yet/,
        );
      }
      await expect(within(progress).getByRole('button', { name: 'Check progress' })).toBeVisible();
    },
  };
}

export const Progress14LiveMonitorRan = monitorStory('14 · Live monitor ran', true);
export const Progress15LiveMonitorHasNotRun = monitorStory('15 · Live monitor has not run', false);

export const AMidFlightReadingStaysProvisionalAfterTheSessionGoesQuiet: Story = {
  ...scenario({
    session: { ...READ({ goal: DEPARTS }, 'mid-flight'), state: 'idle' },
    facts: [PERSON, FAILED],
    work: { analysis_levels: [analysisRow('claude', 'medium')] },
  }),
  play: async ({ canvasElement }) => {
    const progress = await progressCard(canvasElement);
    const header = canvasElement.querySelector('.next-session-detail-header');
    await expect(
      await within(progress).findByText(/^So far, Compass found 1 departure/),
    ).toBeVisible();
    await expect(header).toHaveTextContent('Slightly off course so far');
  },
};
