import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import { neverDone } from './drift.checks';
import {
  DEPARTURE_READING,
  DriftScenario,
  fact,
  passedCheck,
  type Scenario,
} from './drift.scenario';

/* A message the reader sent while the agent worked, and the reader's answer to the agent's question, reach the
   page as the reader's own entries. Claude Code records neither as a user turn, so before this the page showed
   `Later directions: none` and a stored reading named the agent's compliance as its departure. The facts below
   are what the collector publishes for the two records (`test_mid_turn_directions`): a person's `user_message`
   with its own source label, the mid-turn one dated when the reader typed it. The stored reading is the one a
   reader sees after both: nothing departs, and the page asks about the two directions as it asks about any
   later one. */

const meta = {
  title: 'Drift/Mid-turn messages and answers',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const MID_TURN_WORDS = 'Also prune the dead rules from the stylesheets.';
const ANSWER_WORDS = 'Provenance: Defer to a follow-up';

const PERSON = fact('u1', 200, {
  type: 'user_message',
  by: 'person:me',
  summary: 'Tighten the coverage gate',
});
const PASSED = passedCheck('c2', 1010);
const MID_TURN = fact('u2', 1050, {
  type: 'user_message',
  by: 'person:me',
  summary: MID_TURN_WORDS,
  evidence: { source: 'message the reader sent while the agent worked', confidence: 'exact' },
});
const ANSWER = fact('u3', 1100, {
  type: 'user_message',
  by: 'person:me',
  summary: ANSWER_WORDS,
  evidence: { source: "reader's answer to the agent's question", confidence: 'exact' },
});

/* Read after both directions arrived, as the walk's was: the reading finds nothing against the goal, and does
   not name the deferral the reader chose or the pruning the reader asked for as the agent's own. */
const reading = {
  ...DEPARTURE_READING,
  read_at: 1200,
  evidence_through: 1200,
  stamp: 'claude-sonnet-5-5 · read at 09:38',
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
};

const scenario: Scenario = {
  session: { annotation_assessment: reading, annotation_reading_count: 1 },
  facts: [PERSON, PASSED, MID_TURN, ANSWER],
};

export const TheReadersDirectionsAreNotTheAgentsDrift: Story = {
  args: { scenario },
  play: async ({ canvasElement }) => {
    const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
    const shown = await waitFor(() => {
      const node = drift.querySelector<HTMLElement>('[data-next-result]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    // Nothing departs: the stored reading blames the agent for neither direction.
    await expect(shown.querySelectorAll('[data-next-departure]')).toHaveLength(0);
    // Both are the reader's later directions, which the page asks about before it reads on.
    await expect(await within(drift).findByText('2 later directions:')).toBeVisible();
    // Each is a row in Full activity under the reader's own words, never the agent's.
    for (const [id, words] of [
      ['u2', MID_TURN_WORDS],
      ['u3', ANSWER_WORDS],
    ] as const) {
      const row = await waitFor(() => {
        const node = document.querySelector<HTMLElement>(`[data-next-entry-id="${id}"]`);
        expect(node).not.toBeNull();
        return node as HTMLElement;
      });
      await expect(row.textContent).toContain(words);
      await expect(row.textContent).not.toMatch(/Agent said|Agent message/);
    }
    await neverDone(shown);
  },
};
