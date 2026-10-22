import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  fact,
  failedCheck,
  passedCheck,
  type Scenario,
} from './drift.scenario';

/* The harness's own "goal met" verdict on the Drift card. It is Claude Code's claim, labelled as that, and
   Compass's own check of it stands beside it where a reading made one: agreeing, disputed or unconfirmed. It
   never draws a level and never counts as a passing check, and where there is no analysis yet the card says
   the claim has not been checked. */

const meta = {
  title: 'Drift/Harness goal verdict',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

const VERDICT_AT = 1_000;
const GOAL = { text: 'findings.md exists and the retry tests pass', at: 120 };
const REASON = 'findings.md was written and the retry tests pass';
const claimed = {
  session_goal: { ...GOAL, verdict: { met: true, at: VERDICT_AT, reason: REASON } },
};
const PERSON = fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' });
const FACTS = [PERSON, failedCheck('c1', 500), passedCheck('c2', 600)];
/* The level the server derives from the stored reading: Compass's own, which a claim never moves. */
const HIGH = { analysis_levels: [analysisRow('claude')] };
const checked = (check: string, why: string, at = VERDICT_AT) => ({
  annotation_assessment: {
    ...DEPARTURE_READING,
    goal_verdict: { at, check, why, cites: [] },
  },
  annotation_reading_count: 1,
});

const note = async (canvasElement: HTMLElement): Promise<HTMLElement> =>
  waitFor(() => {
    const node = canvasElement.querySelector<HTMLElement>('[data-next-goal-verdict]');
    if (!node) throw new Error('no verdict note');
    return node;
  });

export const ClaimBeforeAnyAnalysis: Story = {
  ...scenario({ session: claimed }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'claim-only');
    // Labelled as the harness's claim, in the reader's words, and no level is implied.
    await expect(node).toHaveTextContent(
      /The harness’s claim: Claude Code marked this goal met at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}\./,
    );
    await expect(node).toHaveTextContent('Compass has not analyzed this session');
    await expect(node).toHaveTextContent(`Its reason: “${REASON}”`);
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
    await expect(node.textContent).not.toMatch(/\b(Low|Medium|High)\b/);
  },
};

export const ClaimBesideAnAgreeingAnalysis: Story = {
  ...scenario({
    session: { ...claimed, ...checked('agrees', 'written-before') },
    facts: FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'agrees');
    await expect(node).toHaveTextContent('The harness’s claim: Claude Code marked this goal met');
    await expect(node).toHaveTextContent(
      'Compass agrees: the file its reason names is recorded as written before the verdict.',
    );
    // The agreement is not a check and does not move the level the analysis found.
    await expect(node).toHaveTextContent('does not change the level and is not a passing check');
    // The record loads after the card, so the level waits for the entries it cites.
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-verdict]')).toHaveTextContent(
        /^High: 1 departure/,
      ),
    );
  },
};

export const ClaimDisputedWhereTheRecordUndoesIt: Story = {
  ...scenario({
    session: { ...claimed, ...checked('disputed', 'written-after') },
    facts: FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'disputed');
    await expect(node).toHaveTextContent(
      'Compass disputes it: the file its reason names was written again after the verdict.',
    );
    await expect(node).toHaveTextContent('Compass’s own reading stands.');
    // Compass's level is the analysis's, untouched by the claim.
    // The record loads after the card, so the level waits for the entries it cites.
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-drift-verdict]')).toHaveTextContent(
        /^High: 1 departure/,
      ),
    );
  },
};

export const ClaimTheRecordCannotConfirm: Story = {
  ...scenario({
    session: { ...claimed, ...checked('unconfirmed', 'not-found') },
    facts: FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'unconfirmed');
    await expect(node).toHaveTextContent(
      'Compass could not confirm it: the record Compass read does not show what its reason names.',
    );
    await expect(node.textContent).not.toContain('disputes');
  },
};

export const ClaimNewerThanTheReading: Story = {
  ...scenario({
    session: { ...claimed, ...checked('agrees', 'written-before', VERDICT_AT - 100) },
    facts: FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'unchecked');
    await expect(node).toHaveTextContent('Analyze again to check it');
    await expect(node.textContent).not.toContain('Compass agrees');
  },
};

export const NoNoteWithoutAMetVerdict: Story = {
  ...scenario({ session: { session_goal: GOAL } }),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('button', { name: 'Analyze drift' });
    await expect(canvasElement.querySelector('[data-next-goal-verdict]')).toBeNull();
  },
};
