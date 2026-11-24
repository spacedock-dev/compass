import { openSessionTechnicalTab } from './sessionTechnical';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { LIVE_HINT, LIVE_MONITOR_DETAILS } from '../src/drift/sentences';
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

/* A reader starts with the progress answer, opens Evidence to check the quote and what was read, and uses
   the shared AI controls or a correction when needed. The Sessions row still names its own state. */

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
  return within(canvasElement).findByRole('region', { name: 'Is it on track?' });
}

const before = (a: Element | null, b: Element | null) =>
  Boolean(a && b && a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

/* Finding 7: one plain sentence leads, What quotes the entry, and the noise moved out of the way. */
export const TheAnswerFirstAndWhatQuotesTheAgent: Story = {
  ...scenario({ session: TWO_DEPARTURES, facts: [PERSON, PASSED, AGENT], work: MEDIUM }),
  play: async ({ canvasElement }) => {
    const progress = await card(canvasElement);
    const heading = within(progress).getByRole('heading', { name: 'Is it on track?' });
    const finding = await within(progress).findByRole('heading', {
      name: 'Where it went off course',
    });
    const level = progress.querySelector('[data-next-drift-pill]');
    await expect(level).toHaveTextContent('Slightly off course');
    await expect(before(heading, level)).toBe(true);
    await expect(before(level, finding)).toBe(true);
    await expect(progress).toHaveTextContent(
      /Compass found 2 departures, both at the agent's message at/,
    );
    await expect(progress).not.toHaveTextContent(SAID);
    await userEvent.click(
      within(progress).getByRole('button', { name: 'See the quote behind this' }),
    );
    const drift = await within(canvasElement).findByRole('tabpanel', { name: 'Evidence' });
    await waitFor(() => expect(drift).toBeVisible());
    const verdict = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-drift-verdict]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(verdict).toHaveTextContent(
      `Medium: 2 departures, both at the agent's message at ${clock(650)}.`,
    );
    await expect(verdict).toBeVisible();
    // In Evidence, the verdict leads the supporting details.
    await expect(before(verdict, drift.querySelector('[data-next-drift-level]'))).toBe(true);
    const whats = [...drift.querySelectorAll<HTMLElement>('[data-next-departure-what]')];
    await expect(whats).toHaveLength(2);
    const citations = whats.map((what) =>
      within(what).getByRole('link', { name: /Show .* in Activity log/ }),
    );
    await waitFor(() => expect(citations[0]).toHaveFocus());
    for (const what of whats) {
      await expect(what).toHaveTextContent(/#\d+/);
      await expect(what).toHaveTextContent(`Agent said: “${SAID}”`);
      await expect(what).toHaveTextContent(clock(650));
      await expect(
        within(what).getByRole('link', { name: /Show .* in Activity log/ }),
      ).toBeVisible();
    }
    // Said once, inside What the check read, not between the verdict and the cards.
    await expect(drift.querySelector('[data-next-departure-status]')).toBeNull();
    await expect(drift.querySelector('[data-next-reading-coverage]')).toBeNull();
    const read = drift.querySelector('[data-next-read-section="session"]') as HTMLElement;
    await expect(read.textContent).toContain('The adopted source was found.');
    await expect(read.textContent).toMatch(/Entries read: #\d+/);
    await expect(
      drift.querySelector('[data-next-drift-level] .next-session-drift-range'),
    ).toBeNull();
    // The quote is the agent's, attributed: the result's own words still never say the work was done.
    const outsideWhat = drift.cloneNode(true) as HTMLElement;
    for (const node of outsideWhat.querySelectorAll('[data-next-departure-what], [data-next-read]'))
      node.remove();
    await neverDone(outsideWhat);
    // The switch announces the cadence and model route in AI use and privacy.
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    await expect(
      await privacy.findByRole('switch', { name: 'Live monitor' }),
    ).toHaveAccessibleDescription(`${LIVE_HINT} ${LIVE_MONITOR_DETAILS}`);
  },
};

/* A departure card draws its cited entry as one line in its own words with its number, and has no Evidence or
   Source fold (owner, 2026-10-23: the citations are the source). Recorded times are local. */
export const ADepartureCardHasNoEvidenceOrSourceFold: Story = {
  ...scenario({ session: TWO_DEPARTURES, facts: [PERSON, PASSED, AGENT], work: MEDIUM }),
  play: async ({ canvasElement }) => {
    await openSessionTechnicalTab('Evidence', canvasElement);
    const drift = canvasElement;
    const goal = drift.querySelector('[data-next-departure="goal"]') as HTMLElement;
    await expect(within(goal).queryByRole('button', { name: /^(Evidence|Source)/ })).toBeNull();
    const line = goal.querySelector('[data-next-cited-entries] > li') as HTMLElement;
    await expect(line).toHaveTextContent(new RegExp(`^Agent said: “.+”#\\d+${clock(650)}$`));
    await expect(goal.textContent).not.toContain('UTC');
    await expect(goal.textContent).not.toContain('Evidence recorded at');
    await expect(goal.textContent).not.toContain('Departs; evidence');
  },
};

/* Finding 14: the progress answer still leads after a later direction, and Evidence names the message the
   check predates. */
export const TheProgressAnswerStaysFirstOverALaterDirection: Story = {
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
    const stale = await within(drift).findByText('Out of date');
    const question = await waitFor(() => {
      const node = drift.querySelector('[data-next-cockpit-direction-question]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(before(stale, question)).toBe(true);
    await expect(drift.querySelector('[data-next-drift-pill]')).toBeNull();
    await openSessionTechnicalTab('Evidence', canvasElement);
    const staleEvidence = canvasElement.querySelector('[data-next-evidence-stale]');
    await expect(staleEvidence).toBeVisible();
    await expect(staleEvidence).toHaveTextContent(`Read before your message at ${clock(1100)}.`);
  },
};

/* Finding 14: when new work makes the saved check stale, the card shows the reader one way to request a new check. */
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
    const stale = await within(drift).findByText('Out of date');
    const [again, inCard] = await within(canvasElement).findAllByRole('button', {
      name: 'Check progress again',
    });
    await expect(stale).toBeVisible();
    await expect(again).toBeVisible();
    await expect(again?.closest('header')).not.toBeNull();
    // The one label, in the header and again in the card beside the stale banner (owner, 2026-11-24).
    await expect(drift.contains(inCard ?? null)).toBe(true);
    await expect(within(canvasElement).getAllByRole('button', { name: /^Check progress/ })).toEqual(
      [again, inCard],
    );
  },
};

/* Pause is in AI use and privacy and in What is sent. Using the copy in What is sent closes the disclosure,
   and the card offers Resume. Evidence reports the number of checks requested. */
export const PauseInTheHeadAndTheDisclosureCloses: Story = {
  ...scenario({
    session: TWO_DEPARTURES,
    facts: [PERSON, PASSED, AGENT],
    work: MEDIUM,
    reading: readingScenario([]),
  }),
  play: async ({ canvasElement }) => {
    const drift = await card(canvasElement);
    const head = drift.querySelector('header') as HTMLElement;
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(await evidence.findByText('2 drift checks requested')).toBeVisible();
    await expect(evidence.queryByText('model requests')).toBeNull();
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    await expect(privacy.getByRole('switch', { name: 'Pause all AI use' })).toBeVisible();
    const summary = within(drift).getByRole('button', { name: /^What is sent/ });
    await userEvent.click(summary);
    const sent = document.getElementById(
      summary.getAttribute('aria-controls') ?? '',
    ) as HTMLElement;
    const inside = await waitFor(() => {
      const found = within(sent).getByRole('button', { name: 'Pause all AI use' });
      expect(found).toBeVisible();
      return found;
    });
    await userEvent.click(inside);
    await waitFor(() =>
      expect(
        within(document.body)
          .queryAllByRole('button', { name: /AI use/ })
          .filter((node) => node.closest('[data-slot="accordion-content"]'))
          .filter((node) => node.checkVisibility()),
      ).toEqual([]),
    );
    const resume = await within(head).findByRole('button', { name: 'Resume AI use' });
    await expect(resume).toBeVisible();
    await expect(within(drift).getAllByRole('button', { name: 'Resume AI use' })).toEqual([resume]);
  },
};

/* A reading that found nothing against the intent: its stories are in DriftLevelNeedsDeparture. */
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
    const copy = await within(drift).findByRole('button', { name: 'Copy message' });
    await userEvent.click(copy);
    await waitFor(() => expect(copy).toHaveTextContent('Copied'));
    await waitFor(() => expect(copy).toHaveTextContent(/^Copy message$/), { timeout: 4000 });
  },
};

/* The level belongs to the focused session, including after the reader returns to Sessions. */
const SESSIONS_NAV: { back?: () => void } = {};
export const TheLevelStaysOnTheSessionPage: Story = {
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
    await expect(within(first).getByRole('img', { name: 'Working' })).toBeVisible();
    await expect(first.textContent).not.toContain('Exact location not published');
    await expect(first.textContent).not.toMatch(/NOW · |QUIET/);
    await expect(within(first).queryByText('Slightly off course')).toBeNull();
    await expect(first.querySelector('.next-operation-progress')).toBeNull();
    await userEvent.click(first.querySelector('a.next-operation-route') as HTMLElement);
    const drift = await card(canvasElement);
    await waitFor(() =>
      expect(drift.querySelector('[data-next-drift-pill]')).toHaveTextContent(
        'Slightly off course',
      ),
    );
    SESSIONS_NAV.back?.();
    const back = await row();
    await expect(within(back).queryByText('Slightly off course')).toBeNull();
    await expect(back.querySelector('.next-operation-progress')).toBeNull();
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
    const drift = await card(canvasElement);
    await waitFor(() =>
      expect(drift.querySelector('[data-next-drift-pill]')).toHaveTextContent('On track'),
    );
    RAISE_NAV.back?.();
    const back = await row();
    await expect(back.querySelector('[data-slot="badge"]')).toBeNull();
  },
};
