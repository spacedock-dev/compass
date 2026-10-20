import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { LIVE_HINT } from '../src/drift/sentences';
import { clock } from '../src/observed';
import { neverDone } from './drift.checks';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  fact,
  passedCheck,
  readingScenario,
  type Scenario,
} from './drift.scenario';

/* The Drift card and the Sessions row after the 2026-10-20 usability review
   (docs/design-reading-a-session.md#amended-2026-10-20-the-answer-first-and-what-quotes-the-entry). Each story
   is one finding: the answer first in one sentence, What quoting the entry, the level always first, the
   stale banner naming the message it predates with Check again beside it, Evidence's heading and local
   times, Pause model calls in the card's head, the count's honest name, a Copied cue that lapses, and the
   Sessions row's one state word and drift level. */

const meta = {
  title: 'Drift/Usability review, 2026-10-20',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });
const PASSED = passedCheck('c2', 600);
const SAID = 'Done: the billing rate is now 0.25 in src/billing/invoice.ts.';
const AGENT = fact('m5', 650, { type: 'agent_message', by: 'agent', summary: SAID });

/* Two departures, both resting on the agent's one message, as in the review's session. */
const TWO_DEPARTURES = {
  annotation_assessment: {
    ...DEPARTURE_READING,
    stamp: 'claude-sonnet-5-5 · read at 09:38',
    coverage: { ...DEPARTURE_READING.coverage, goal_source: 'whole' },
    criteria: {
      goal: {
        result: 'departure',
        cites: ['m5'],
        detail: 'The agent edited the billing module it was told not to touch.',
        clause: 'Ship the queue',
      },
      line_1: {
        result: 'departure',
        cites: ['m5'],
        detail: 'The outcome line says tests pass and billing is unchanged.',
        clause: 'Tests pass',
      },
    },
  },
  annotation_reading_count: 2,
};
const MEDIUM = {
  analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'], cites: ['m5'] }],
};

async function card(canvasElement: HTMLElement): Promise<HTMLElement> {
  const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
  await waitFor(() => expect(drift.querySelector('[data-next-result]')).not.toBeNull());
  return drift;
}

const before = (a: Element | null, b: Element | null) =>
  Boolean(a && b && a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

/* Finding 7: one plain sentence leads, What quotes the entry, and the noise moved out of the way. */
export const TheAnswerFirstAndWhatQuotesTheAgent: Story = {
  ...scenario({ session: TWO_DEPARTURES, facts: [PERSON, PASSED, AGENT], work: MEDIUM }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const verdict = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-verdict]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(verdict).toHaveTextContent(
      `Medium: 2 departures, both at the agent's message at ${clock(650)}.`,
    );
    await expect(verdict).toBeVisible();
    // Under the heading, ahead of the level and the result.
    await expect(before(drift.querySelector('header'), verdict)).toBe(true);
    await expect(before(verdict, drift.querySelector('[data-next-drift-level]'))).toBe(true);
    const whats = [...drift.querySelectorAll<HTMLElement>('[data-next-departure-what]')];
    await expect(whats).toHaveLength(2);
    for (const what of whats) {
      await expect(what).toHaveTextContent(/#\d+/);
      await expect(within(what).getByText(`Agent said: “${SAID}”`)).toBeVisible();
    }
    // Said once, inside Evidence and What the analysis read, not between the verdict and the cards.
    await expect(drift.querySelector('[data-next-departure-status]')).toBeNull();
    await expect(drift.querySelector('[data-next-reading-coverage]')).toBeNull();
    const read = drift.querySelector('[data-next-read-section="session"]') as HTMLElement;
    await expect(read.textContent).toContain('The adopted source was found.');
    await expect(read.textContent).toMatch(/Entries read: #\d+/);
    await expect(
      drift.querySelector('[data-next-drift-level] .next-session-drift-range'),
    ).toBeNull();
    // The monitor's description is its switch's helper text.
    const head = drift.querySelector('header') as HTMLElement;
    await expect(
      within(head).getByRole('switch', { name: 'Live monitor' }),
    ).toHaveAccessibleDescription(LIVE_HINT);
    // The quote is the agent's, attributed: the result's own words still never say the work was done.
    const outsideWhat = drift.cloneNode(true) as HTMLElement;
    for (const node of outsideWhat.querySelectorAll('[data-next-departure-what], [data-next-read]'))
      node.remove();
    await neverDone(outsideWhat);
  },
};

/* Finding 9: Evidence heads with the line's label in a sentence's case, then the entry by number, kind and
   time; the record-type tag is under Source; recorded times are local. */
export const EvidenceReadsAsAHeadingThenTheEntry: Story = {
  ...scenario({ session: TWO_DEPARTURES, facts: [PERSON, PASSED, AGENT], work: MEDIUM }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const goal = drift.querySelector('[data-next-departure="goal"]') as HTMLElement;
    await userEvent.click(within(goal).getByRole('button', { name: 'Evidence' }));
    const head = await waitFor(() => {
      const node = goal.querySelector<HTMLElement>('[data-next-evidence-head]');
      expect(node).toBeVisible();
      return node as HTMLElement;
    });
    await expect(head.textContent).toMatch(/^[A-Z][a-z ]+$/);
    await expect(goal.querySelector('.next-cockpit-assessment-entry')).toHaveTextContent(
      new RegExp(`^#\\d+ · Agent message · ${clock(650)}$`),
    );
    await expect(goal.textContent).not.toContain('UTC');
    await expect(goal.textContent).toContain('Departs; evidence #');
  },
};

/* Finding 14: a later direction's question no longer moves the level below it, and the stale banner names
   the message the check predates. */
export const TheLevelStaysFirstOverALaterDirection: Story = {
  ...scenario({
    session: TWO_DEPARTURES,
    facts: [
      PERSON,
      PASSED,
      AGENT,
      fact('u2', 1100, {
        type: 'user_message',
        by: 'person:me',
        summary: 'Please revert the billing change.',
      }),
    ],
    work: MEDIUM,
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const question = await waitFor(() => {
      const node = drift.querySelector('[data-next-cockpit-direction-question]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    const level = drift.querySelector('[data-next-drift-level]');
    await expect(before(drift.querySelector('[data-next-drift-verdict]'), level)).toBe(true);
    await expect(before(level, question)).toBe(true);
    await expect(drift.querySelector('[data-next-result-stale]')).toHaveTextContent(
      `This check is from before your ${clock(1100)} message.`,
    );
  },
};

/* Finding 14: new work with no message from the reader: Check again stands beside the banner. */
export const CheckAgainBesideTheStaleBanner: Story = {
  ...scenario({
    session: TWO_DEPARTURES,
    facts: [
      PERSON,
      PASSED,
      AGENT,
      fact('m6', 1250, { type: 'agent_message', by: 'agent', summary: 'Still going.' }),
    ],
    work: MEDIUM,
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const stale = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-result-stale]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    const again = within(stale).getByRole('button', { name: 'Check again' });
    await expect(again).toBeVisible();
    await expect(within(drift).getAllByRole('button', { name: /^(Analyze|Check again)/ })).toEqual([
      again,
    ]);
  },
};

/* Finding 13: Pause model calls is in the card's head in every state; the copy in What is sent closes its
   popover when pressed, and the head then offers Resume. Finding 12: the count says what it counts. */
export const PauseInTheHeadAndThePopoverCloses: Story = {
  ...scenario({
    session: TWO_DEPARTURES,
    facts: [PERSON, PASSED, AGENT],
    work: MEDIUM,
    reading: readingScenario([]),
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const head = drift.querySelector('header') as HTMLElement;
    await expect(within(head).getByRole('button', { name: 'Pause model calls' })).toBeVisible();
    await expect(drift).toHaveTextContent('2 drift checks requested');
    await expect(drift.textContent).not.toContain('model requests');
    await userEvent.click(within(drift).getByRole('button', { name: /^What is sent/ }));
    const inside = await waitFor(() => {
      const found = within(document.body)
        .getAllByRole('button', { name: 'Pause model calls' })
        .find((node) => node.closest('[data-slot="popover-content"]'));
      expect(found).toBeVisible();
      return found as HTMLElement;
    });
    await userEvent.click(inside);
    await waitFor(() =>
      expect(
        within(document.body)
          .queryAllByRole('button', { name: /model calls/ })
          .filter((node) => node.closest('[data-slot="popover-content"]'))
          .filter((node) => node.checkVisibility()),
      ).toEqual([]),
    );
    const resume = await within(head).findByRole('button', { name: 'Resume model calls' });
    await expect(resume).toBeVisible();
    await expect(within(drift).getAllByRole('button', { name: 'Resume model calls' })).toEqual([
      resume,
    ]);
  },
};

/* A Medium level with no departure (a contradicted claim, here) says why the level stands rather than
   "Medium: Nothing found", which contradicted its own word. */
const CONSISTENT_READING = {
  annotation_assessment: {
    ...DEPARTURE_READING,
    criteria: {
      goal: {
        result: 'consistent with the evidence read',
        cites: ['c2'],
        detail: '',
        clause: 'Ship the queue',
      },
      line_1: {
        result: 'consistent with the evidence read',
        cites: ['c2'],
        detail: '',
        clause: 'Tests pass',
      },
    },
  },
  annotation_reading_count: 1,
};
export const MediumWithNoDepartureSaysWhy: Story = {
  ...scenario({
    session: CONSISTENT_READING,
    facts: [PERSON, PASSED, AGENT],
    work: {
      analysis_levels: [
        { ...analysisRow('claude', 'medium'), reasons: ['claim-contradicted'], cites: ['m5'] },
      ],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const verdict = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-verdict]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(verdict).toHaveTextContent(
      /^Medium: No departure from your intent\. The record contradicts what the agent said/,
    );
    await expect(verdict.textContent).not.toContain('Nothing found');
    await expect(verdict).toBeVisible();
  },
};

/* Finding 20: "Copied" answers one press. It lapses back to Copy, and a box drawn again starts at Copy. */
export const CopiedLapsesBackToCopy: Story = {
  ...scenario({
    session: TWO_DEPARTURES,
    facts: [PERSON, PASSED, AGENT],
    work: MEDIUM,
    clipboard: true,
    correction: {
      ok: true,
      parts: ['Back to my goal: Ship the queue\nPlease continue from here.'],
    },
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    await userEvent.click(await within(drift).findByRole('button', { name: 'Steer back' }));
    const copy = await within(drift).findByRole('button', { name: 'Copy' });
    await userEvent.click(copy);
    await waitFor(() => expect(copy).toHaveTextContent('Copied'));
    await waitFor(() => expect(copy).toHaveTextContent(/^Copy$/), { timeout: 4000 });
  },
};

/* Findings 8 and 17: a Sessions row leads with one state word and shows the project label alone, and its
   drift chip names a level: before this tab has read the project, the least a departure reads (a departure
   reads Medium unless a fresh failed check makes it High) with no meter, and once it has, the level the
   session header names, from the same derivation. */
const SESSIONS_NAV: { back?: () => void } = {};
export const TheSessionsRowSaysTheLevel: Story = {
  ...scenario({
    initialView: 'sessions',
    session: TWO_DEPARTURES,
    facts: [PERSON, PASSED, AGENT],
    work: MEDIUM,
    nav: SESSIONS_NAV,
  }),
  play: async ({ canvasElement }) => {
    const row = async () =>
      waitFor(() => {
        const node = canvasElement.querySelector<HTMLElement>('article.next-operation-row');
        expect(node).not.toBeNull();
        return node as HTMLElement;
      });
    const first = await row();
    // The scenario's session publishes `working`.
    await expect(first.querySelector('[data-next-row-state]')).toHaveTextContent(/^Working$/);
    await expect(first.querySelector('[data-next-row-state]')).toBeVisible();
    await expect(first.textContent).not.toContain('Exact location not published');
    await expect(first.textContent).not.toMatch(/NOW · |QUIET/);
    await expect(first.querySelector('[data-next-session-drift-mark]')).toHaveTextContent(
      /^Drift: Medium or higher · /,
    );
    await expect(
      first.querySelector('[data-next-row-drift-level="medium_or_higher"]'),
    ).not.toBeNull();
    await expect(first.querySelector('.next-session-drift-pill-meter')).toBeNull();
    await userEvent.click(first.querySelector('a.next-operation-route') as HTMLElement);
    await card(canvasElement);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-pill]')).toHaveTextContent(
        'Drift: Medium',
      ),
    );
    const pill = canvasElement.querySelector('[data-next-drift-pill] strong')?.textContent;
    SESSIONS_NAV.back?.();
    const back = await row();
    await waitFor(() =>
      expect(back.querySelector('[data-next-row-drift-level="medium"]')).not.toBeNull(),
    );
    await expect(back.querySelector('[data-next-session-drift-mark] strong')).toHaveTextContent(
      pill ?? 'missing',
    );
    await expect(back.querySelector('.next-session-drift-pill-meter')).not.toBeNull();
  },
};

/* A raise beside a reading that does not depart names no level: the chip once borrowed the consistent
   reading's "None or low" once this tab held its analysis, beside a recorded departure. */
const RAISE_NAV: { back?: () => void } = {};
export const ARaiseAloneNamesNoLevel: Story = {
  ...scenario({
    initialView: 'sessions',
    session: { ...CONSISTENT_READING, departures: [{ at: 900, revision: 3 }] },
    facts: [PERSON, PASSED, AGENT],
    work: {
      analysis_levels: [{ ...analysisRow('claude', 'none_or_low'), reasons: [], cites: [] }],
    },
    nav: RAISE_NAV,
  }),
  play: async ({ canvasElement }) => {
    const row = async () =>
      waitFor(() => {
        const node = canvasElement.querySelector<HTMLElement>('article.next-operation-row');
        expect(node).not.toBeNull();
        return node as HTMLElement;
      });
    await userEvent.click((await row()).querySelector('a.next-operation-route') as HTMLElement);
    await card(canvasElement);
    RAISE_NAV.back?.();
    const back = await row();
    const mark = back.querySelector('[data-next-session-drift-mark]');
    await expect(mark).toHaveTextContent(/^Drift · /);
    await expect(mark?.querySelector('[data-next-row-drift-level]')).toBeNull();
  },
};
