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

/* A correction the reader pastes back into the session is Compass's own words, and the card treats it so.
   Claude Code wraps a paste in `<pasted_content id="N">` tags, which the server strips before it matches a
   pasted correction against the ones Compass built and before it publishes a direction; a server or a
   history that still sends them must not put the tags in front of the reader either, on any surface that
   draws a message's words: the direction select, a quote of a cited message and the work list. The sentence
   a correction earns when the next reading no longer finds the departure it named, and when it finds a
   different one in its place, follow. */

const meta = {
  title: 'Drift/A pasted correction',
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

const WRAPPER = /pasted_content/;
const WRAPPED =
  '\n\n<pasted_content id="3">\nBack to my goal: Ship the queue, and leave the stylesheets alone.\n</pasted_content>\n';

/* A direction the reader gave after saving their intent, whose whole words arrive wrapped. Keep draws them
   before it settles anything, which is where the walk saw the tags. */
export const AWrappedDirectionIsQuotedWithoutItsWrapper: Story = {
  ...scenario({
    session: { annotation_assessment: DEPARTURE_READING, annotation_reading_count: 1 },
    facts: [
      PERSON,
      FAILED,
      PASSED,
      fact('u2', 1050, {
        type: 'user_message',
        by: 'person:me',
        summary: '<pasted_content id="3"> Back to my goal: Ship the queue',
      }),
    ],
    directionText: WRAPPED,
  }),
  play: async ({ canvasElement }) => {
    const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
    await within(drift).findByText(/^Your \d\d:\d\d message adds:$/);
    await expect(drift.textContent).not.toMatch(WRAPPER);
    const whole = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-cockpit-direction-whole]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(whole).toHaveTextContent(
      'Back to my goal: Ship the queue, and leave the stylesheets alone.',
    );
    await expect(whole.textContent).not.toMatch(WRAPPER);
    await expect(drift.textContent).not.toMatch(WRAPPER);
  },
};

/* The steer worked: a correction the server recognised as Compass's own words (`copied`) sits between the two
   readings, and the second reading no longer finds the departure the first one carried. The card says the steer
   named it, with the time of the reading it came from, and the correction is no later direction of the reader's. */
const STEERED_SESSION: Record<string, unknown> = {
  annotation_assessment: DEPARTURE_READING,
  annotation_reading_count: 1,
  state: 'idle',
};
const STEERING = readingScenario([null]);
const CANT_TELL = {
  result: 'not verifiable from available evidence',
  cites: [],
  detail: '',
  clause: 'Tests pass',
};
export const ADepartureTheSteerNamedIsSaidToBeGone: Story = {
  ...scenario({
    session: STEERED_SESSION,
    facts: [
      PERSON,
      FAILED,
      PASSED,
      AGENT,
      fact('p1', 1050, {
        type: 'user_message',
        by: 'person:me',
        copied: true,
        summary: 'Back to my goal: Ship the queue',
      }),
    ],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: STEERING,
  }),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull();
    // The pasted correction is Compass's words: no later direction is asked about.
    await expect(canvasElement.querySelector('[data-next-cockpit-direction-question]')).toBeNull();
    STEERED_SESSION['annotation_assessment'] = {
      ...DEPARTURE_READING,
      read_at: 1100,
      evidence_through: 1100,
      criteria: { goal: { ...CANT_TELL, clause: 'Ship the queue' }, line_1: CANT_TELL },
    };
    await STEERING.finish?.();
    const cleared = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-cleared]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(cleared).toHaveTextContent(
      `The departure your correction named, from the ${clock(1000)} reading, no longer holds.`,
    );
  },
};

/* Messages whose published titles still carry the tags: the first the opening of a paste whose tag leads, the
   second a paste whose tag shares a line with the reader's typed words. Each is a reader's own words, not a
   correction Compass built, so each is a later direction and each can be cited. */
const LEADING = fact('u2', 1050, {
  type: 'user_message',
  by: 'person:me',
  summary: '<pasted_content id="3"> Back to my goal: Ship the queue',
});
const INLINE = fact('u3', 1100, {
  type: 'user_message',
  by: 'person:me',
  summary: 'Also, <pasted_content id="4">prune the stylesheets',
});

/* More than one later direction opens the picker, whose trigger names the earliest in its title and whose
   options name each. Neither says the harness's tags. */
export const TheDirectionSelectDrawsNoWrapper: Story = {
  ...scenario({
    session: { annotation_assessment: DEPARTURE_READING, annotation_reading_count: 1 },
    facts: [PERSON, FAILED, PASSED, LEADING, INLINE],
  }),
  play: async ({ canvasElement }) => {
    const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
    const trigger = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-direction-select]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    // The title names the direction the picker holds, whichever of the two it opens on.
    await expect(trigger.getAttribute('title')).toMatch(
      /^(Back to my goal: Ship the queue|Also, prune the stylesheets)$/,
    );
    await userEvent.click(trigger);
    const options = await within(document.body).findAllByRole('option');
    await expect(options.map((option) => option.textContent)).toEqual([
      expect.stringContaining('Back to my goal: Ship the queue'),
      expect.stringContaining('Also, prune the stylesheets'),
    ]);
    await expect(document.body.textContent).not.toMatch(WRAPPER);
  },
};

/* A departure that cites the reader's own message quotes it, in the card that opens on its number: "You said",
   then the words, without the tags. */
const CITING_READING = {
  ...DEPARTURE_READING,
  criteria: {
    ...DEPARTURE_READING.criteria,
    goal: { ...DEPARTURE_READING.criteria.goal, cites: ['c1', 'u3'] },
  },
};
export const ACitedMessageIsQuotedWithoutItsWrapper: Story = {
  ...scenario({
    session: { annotation_assessment: CITING_READING, annotation_reading_count: 1 },
    facts: [PERSON, FAILED, PASSED, INLINE],
  }),
  play: async ({ canvasElement }) => {
    const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
    const card = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-departure]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    // The departure card titles itself on the failed check it cites, so the reader's message is quoted in the
    // citation's own card, which opens on its number.
    const citation = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-cite="u3"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(card.textContent).not.toMatch(WRAPPER);
    await userEvent.hover(citation);
    const shown = await waitFor(() => {
      const node = document.querySelector<HTMLElement>('[data-next-citation-card]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(shown.querySelector('[data-next-citation-snippet]')).toHaveTextContent(
      /^You said: “Also, prune the stylesheets”$/,
    );
    await expect(shown.textContent).not.toMatch(WRAPPER);
    await expect(drift.textContent).not.toMatch(WRAPPER);
  },
};

/* Full activity lists each message by the words it carries. */
export const TheWorkListDrawsNoWrapper: Story = {
  ...scenario({
    session: { annotation_assessment: DEPARTURE_READING, annotation_reading_count: 1 },
    facts: [PERSON, FAILED, PASSED, LEADING, INLINE],
  }),
  play: async ({ canvasElement }) => {
    await userEvent.click(
      await within(canvasElement).findByRole('button', { name: 'Full activity' }),
    );
    for (const [id, words] of [
      ['u2', 'Back to my goal: Ship the queue'],
      ['u3', 'Also, prune the stylesheets'],
    ] as const) {
      const row = await waitFor(() => {
        const node = canvasElement.querySelector<HTMLElement>(`[data-next-entry-id="${id}"]`);
        expect(node).not.toBeNull();
        return node as HTMLElement;
      });
      await expect(row).toHaveTextContent(words);
      await expect(row.textContent).not.toMatch(WRAPPER);
    }
  },
};

/* The steer worked on the departure it named, and the next reading departs on something else: a different
   reason, resting on a check that ran after the correction. The card says the correction named the first, with
   the time of the reading it came from, while the new departure stands under it. */
const REPLACED_SESSION: Record<string, unknown> = {
  annotation_assessment: DEPARTURE_READING,
  annotation_reading_count: 1,
  state: 'idle',
};
const REPLACING = readingScenario([null]);
const LATER_FAILURE = fact('c3', 1080, {
  subject: 'check',
  result: 'failed',
  result_source: 'failed flag',
  summary: 'ruff check',
});
export const AReplacedDepartureAfterACorrectionIsNamed: Story = {
  ...scenario({
    session: REPLACED_SESSION,
    facts: [
      PERSON,
      FAILED,
      PASSED,
      LATER_FAILURE,
      AGENT,
      fact('p1', 1050, {
        type: 'user_message',
        by: 'person:me',
        copied: true,
        summary: 'Back to my goal: Ship the queue',
      }),
    ],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: REPLACING,
  }),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull();
    REPLACED_SESSION['annotation_assessment'] = {
      ...DEPARTURE_READING,
      read_at: 1100,
      evidence_through: 1100,
      criteria: {
        goal: {
          result: 'departure',
          cites: ['c3'],
          detail: 'The lint check failed after the correction.',
          clause: 'Ship the queue',
        },
        line_1: DEPARTURE_READING.criteria.line_1,
      },
    };
    await REPLACING.finish?.();
    const cleared = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-cleared]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(cleared).toHaveTextContent(
      `The departure your correction named, from the ${clock(1000)} reading, no longer holds.`,
    );
    // One departure still stands, and it is the new one.
    await expect(canvasElement.querySelectorAll('[data-next-departure]')).toHaveLength(1);
    await expect(canvasElement.textContent).toContain(
      'The lint check failed after the correction.',
    );
  },
};

/* The same replacement with no correction pasted between the two readings: the card names the earlier
   departure all the same, without saying a correction named it. A departure is the same one only on the same
   line with the same reason or a shared cited entry, so a reading that departs on a different failed check
   has not found the first again. */
const UNCORRECTED_SESSION: Record<string, unknown> = {
  annotation_assessment: DEPARTURE_READING,
  annotation_reading_count: 1,
  state: 'idle',
};
const UNCORRECTED = readingScenario([null]);
export const AReplacedDepartureWithNoCorrectionIsNamed: Story = {
  ...scenario({
    session: UNCORRECTED_SESSION,
    facts: [PERSON, FAILED, PASSED, LATER_FAILURE, AGENT],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: UNCORRECTED,
  }),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('region', { name: 'Drift' });
    await expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull();
    UNCORRECTED_SESSION['annotation_assessment'] = {
      ...DEPARTURE_READING,
      read_at: 1100,
      evidence_through: 1100,
      criteria: {
        goal: {
          result: 'departure',
          cites: ['c3'],
          detail: 'The lint check failed after the first reading.',
          clause: 'Ship the queue',
        },
        line_1: DEPARTURE_READING.criteria.line_1,
      },
    };
    await UNCORRECTED.finish?.();
    const cleared = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-cleared]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(cleared).toHaveTextContent(
      `The departure from the ${clock(1000)} reading no longer holds.`,
    );
    await expect(cleared.textContent).not.toMatch(/correction/);
    await expect(canvasElement.querySelectorAll('[data-next-departure]')).toHaveLength(1);
  },
};

/* After the steer, the agent explained the departing edit and the next reading answered the line with that
   message alone: "Consistent with what the agent said at #n; not a check". The store kept the earlier departure
   beside the reading (`annotation_prior_departures`), so the card lists it under the later reading, with the
   write it cited and its reason, and the verdict says it is still listed rather than that it no longer holds.
   A line a check answers after the correction lists nothing, and keeps the sentence the steer earned. */
const STYLES_LINE = 'Leave the stylesheets alone';
const STYLES_WRITE = fact('w1', 650, { subject: 'write', summary: 'src/styles/queue.css' });
const STYLES_DETAIL = 'A stylesheet was written, which this line rules out.';
const STYLES_DEPARTURE = {
  result: 'departure',
  cites: ['w1'],
  detail: STYLES_DETAIL,
  clause: STYLES_LINE,
  why: 'recorded-write',
};
const STYLES_READING = {
  ...DEPARTURE_READING,
  criteria: {
    goal: { ...CANT_TELL, clause: 'Ship the queue' },
    line_1: DEPARTURE_READING.criteria.line_1,
    line_2: STYLES_DEPARTURE,
  },
};
const STYLES_CORRECTION = fact('p1', 1050, {
  type: 'user_message',
  by: 'person:me',
  copied: true,
  summary: 'Back to my goal: Ship the queue, and leave the stylesheets alone.',
});
const EXPLAINED = fact('m6', 1080, {
  type: 'agent_message',
  by: 'agent',
  summary: 'The stylesheet edit was needed for the queue page, so I kept it and committed it.',
});
const RECHECKED = passedCheck('c3', 1090);
const STYLES_PRIOR = [
  { key: 'line_2', read_at: 1000, revision_read: 3, criterion: STYLES_DEPARTURE },
];
const restyled = (line2: Record<string, unknown>) => ({
  ...STYLES_READING,
  read_at: 1100,
  evidence_through: 1100,
  criteria: {
    ...STYLES_READING.criteria,
    line_2: { detail: '', clause: STYLES_LINE, ...line2 },
  },
});
const stylesSession = (): Record<string, unknown> => ({
  annotation_line_2: STYLES_LINE,
  annotation_assessment: STYLES_READING,
  annotation_reading_count: 1,
  state: 'idle',
});

const LISTED_SESSION = stylesSession();
const LISTING = readingScenario([null]);
export const AnEarlierDepartureClearedOnlyByTheAgentStaysListed: Story = {
  ...scenario({
    session: LISTED_SESSION,
    facts: [PERSON, PASSED, STYLES_WRITE, STYLES_CORRECTION, EXPLAINED],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: LISTING,
  }),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-departure="line_2"]')).not.toBeNull(),
    );
    await expect(canvasElement.querySelector('[data-next-prior-departures]')).toBeNull();
    LISTED_SESSION['annotation_assessment'] = restyled({
      result: 'consistent with the evidence read',
      cites: ['m6'],
    });
    LISTED_SESSION['annotation_reading_count'] = 2;
    LISTED_SESSION['annotation_prior_departures'] = STYLES_PRIOR;
    await LISTING.finish?.();
    const group = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-prior-departures]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    const card = group.querySelector<HTMLElement>('[data-next-prior-departure="line_2"]');
    await expect(card).not.toBeNull();
    await expect(card?.querySelector('[data-next-departure-label]')).toHaveTextContent(
      'Earlier departure · Expected outcome 2',
    );
    // What the earlier reading cited and why, through the same card a standing departure draws.
    await expect(card?.querySelector('[data-next-cite="w1"]')).not.toBeNull();
    await expect(card).toHaveTextContent(STYLES_DETAIL);
    await expect(card?.querySelector('[data-next-prior-departure-source]')).toHaveTextContent(
      new RegExp(
        `^From the ${clock(1000)} reading\\. The ${clock(1100)} reading rests this line on what the agent said at #\\d+, which is not a check\\.$`,
      ),
    );
    // No departure stands, and the reader is not told the steer worked.
    await expect(canvasElement.querySelector('[data-next-departures]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-drift-cleared]')).toBeNull();
    await expect(canvasElement.textContent).not.toContain('no longer holds');
    await expect(canvasElement.querySelector('[data-next-drift-prior-listed]')).toHaveTextContent(
      `The departure from the ${clock(1000)} reading is still listed below: the reading after it rests on what the agent said.`,
    );
  },
};

const CHECKED_SESSION = stylesSession();
const CHECKING = readingScenario([null]);
export const AnEarlierDepartureAnsweredByACheckIsNotListed: Story = {
  ...scenario({
    session: CHECKED_SESSION,
    facts: [PERSON, PASSED, STYLES_WRITE, STYLES_CORRECTION, EXPLAINED, RECHECKED],
    work: { analysis_levels: [{ ...analysisRow('claude', 'medium'), reasons: ['departure'] }] },
    reading: CHECKING,
  }),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('region', { name: 'Drift' });
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-departure="line_2"]')).not.toBeNull(),
    );
    CHECKED_SESSION['annotation_assessment'] = restyled({
      result: 'consistent with the evidence read',
      cites: ['c3'],
    });
    CHECKED_SESSION['annotation_reading_count'] = 2;
    // The store keeps it all the same; the page lists it only where the agent's word alone answers the line.
    CHECKED_SESSION['annotation_prior_departures'] = STYLES_PRIOR;
    await CHECKING.finish?.();
    const cleared = await waitFor(() => {
      const node = canvasElement.querySelector<HTMLElement>('[data-next-drift-cleared]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(cleared).toHaveTextContent(
      `The departure your correction named, from the ${clock(1000)} reading, no longer holds.`,
    );
    await expect(canvasElement.querySelector('[data-next-prior-departures]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-drift-prior-listed]')).toBeNull();
  },
};
