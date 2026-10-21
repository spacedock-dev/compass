import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { clock } from '../src/observed';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  fact,
  passedCheck,
  readingScenario,
  type Scenario,
} from './drift.scenario';

/* A level above None or low stands on a departure the reading shows, and a departure that clears is named
   once
   ([the amendment](../../docs/design-reading-a-session.md#amended-2026-10-21-a-level-needs-a-departure)).
   A running turn is unfinished work, so the header pill says "so far" while it runs. Each story is one
   thing a reader sees. */

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

async function card(canvasElement: HTMLElement): Promise<HTMLElement> {
  const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
  await waitFor(() => expect(drift.querySelector('[data-next-result]')).not.toBeNull());
  return drift;
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
    const drift = await card(canvasElement);
    await userEvent.click(
      await within(drift.querySelector('header') as HTMLElement).findByRole('button', {
        name: 'Drift settings',
      }),
    );
    await userEvent.click(
      await within(document.body).findByRole('switch', { name: 'Live monitor' }),
    );
    const verdict = await verdictOf(drift);
    await expect(verdict.textContent).not.toMatch(/Medium|High|Extreme/);
    await waitFor(() => expect(drift.querySelector('[data-next-drift-level]')).toBeNull());
    await expect(drift.querySelector('.next-session-drift-meter')).toBeNull();
    await expect(drift.textContent).not.toMatch(/\bMedium\b/);
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
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
    const drift = await card(canvasElement);
    const verdict = await verdictOf(drift);
    await expect(verdict).toHaveTextContent(
      'Nothing found against what it read, but no level is drawn: a line of your intent is not shown by any check.',
    );
    await expect(drift.textContent).not.toContain('Why not None or low');
    await expect(drift.querySelector('[data-next-drift-level]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
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
    const drift = await card(canvasElement);
    const verdict = await verdictOf(drift);
    await expect(verdict).toHaveTextContent(
      /^Nothing found against what it read, but no level is drawn: the record contradicts what the agent said\./,
    );
    await expect(drift.textContent).not.toMatch(/\bMedium\b/);
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
  },
};

/* A reading that departs keeps its level in the card, and the pill says "so far" while the session runs (the
   scenario's session publishes `working`). */
export const ADepartureKeepsItsLevelAndTheRunningPillSaysSoFar: Story = {
  ...scenario({
    session: READ({ goal: DEPARTS, line_1: CANT_TELL }),
    facts: [PERSON, FAILED, PASSED, AGENT],
    work: {
      analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const verdict = await verdictOf(drift);
    await expect(verdict).toHaveTextContent(/^Medium: 1 departure/);
    // The level's word is the sentence's alone; the meter's head holds its source.
    await expect(drift.querySelector('[data-next-drift-level]')).toHaveTextContent(/^Analysis/);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-pill]')).toHaveTextContent(
        'Drift: Medium so far',
      ),
    );
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
    await card(canvasElement);
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
