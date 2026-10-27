import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import collected from '../test/fixtures/collected-directions.json';
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
   `Later directions: none` and a stored reading named the agent's compliance as its departure.

   The two facts are not written here. They are what the collector published for a transcript holding both
   (`test_mid_turn_directions`, `TheStoryReadsWhatTheCollectorPublishesTest`, which fails when the committed
   file is not what the collector now publishes), and the answer there was the agent's option marked
   `(Recommended)`. A collector that quotes the marker again, or reads the answer as a typed turn, changes the
   file and this story asserts against the change. Only the ids and times are the scenario's. The stored
   reading is the one a reader sees after both: nothing departs, and the page asks about the two directions as
   it asks about any later one. */

const meta = {
  title: 'Drift/Mid-turn messages and answers',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const MID_TURN_WORDS = collected.mid_turn.summary;
const ANSWER_WORDS = collected.answer.summary;

const PERSON = fact('u1', 200, {
  type: 'user_message',
  by: 'person:me',
  summary: 'Tighten the coverage gate',
});
const PASSED = passedCheck('c2', 1010);
/* The collector's ids, times and session are its own transcript's; the scenario places the facts in its own. */
const placed = (
  id: string,
  at: number,
  { source_session: _own, ...published }: typeof collected.answer,
) => fact(id, at, { ...published, fact_id: id, at });
const MID_TURN = placed('u2', 1050, collected.mid_turn);
const ANSWER = placed('u3', 1100, collected.answer);

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
      // The agent's own label on the option the reader picked is not the reader's word.
      await expect(row.textContent).not.toMatch(/recommended/i);
      await expect(row.textContent).not.toMatch(/Agent said|Agent message/);
    }
    // The answer is the option the reader picked, said as they picked it.
    await expect(ANSWER_WORDS).toBe('Ruling: Same folder in its checkout');
    await neverDone(shown);
  },
};
