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
   history that still sends them must not put the tags in front of the reader either. The sentence a steer
   earns when the next reading no longer finds the departure it named is the second story. */

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
    await within(drift).findByText(/1 later direction/);
    await expect(drift.textContent).not.toMatch(WRAPPER);
    await userEvent.click(await within(drift).findByRole('button', { name: /^Keep my intent/ }));
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
      `The departure your steer named, from the ${clock(1000)} reading, no longer holds.`,
    );
  },
};
