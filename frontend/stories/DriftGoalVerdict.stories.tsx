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
const checked = (
  check: string,
  why: string,
  at = VERDICT_AT,
  extra: Record<string, unknown> = {},
) => ({
  annotation_assessment: {
    ...DEPARTURE_READING,
    goal_verdict: { at, check, why, cites: [], ...extra },
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

export const ClaimConfirmedByTheCreatedPullRequest: Story = {
  ...scenario({
    session: {
      session_goal: {
        ...GOAL,
        verdict: { met: true, at: VERDICT_AT, reason: 'the agent created PR #7 and pushed' },
      },
      ...checked('agrees', 'pr-created-before', VERDICT_AT, { cites: ['pr1'] }),
    },
    facts: [...FACTS, fact('pr1', 550, { subject: 'pr', summary: 'example-org/example-repo#7' })],
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'agrees');
    // Names the pull request fact it confirmed, in Compass's words, and is still only the harness's claim.
    await waitFor(() =>
      expect(node).toHaveTextContent(
        'Compass agrees: the pull request its reason names, example-org/example-repo#7, is recorded as created before the verdict.',
      ),
    );
    await expect(node).toHaveTextContent('The harness’s claim: Claude Code marked this goal met');
    await expect(node).toHaveTextContent('does not change the level and is not a passing check');
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

/* The record after the verdict deletes a file the reason names (a real session: the harness said met over a file
   a later turn removed). Compass says disputed and names the file and the moment, where it would otherwise only
   say it could not confirm. */
export const ClaimDisputedByAFileTakenAway: Story = {
  ...scenario({
    session: {
      ...claimed,
      ...checked('disputed', 'deleted-after', VERDICT_AT, {
        path: 'docs/e2e/notes.md',
        changed_at: VERDICT_AT + 90,
      }),
    },
    facts: FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await note(canvasElement);
    await expect(node).toHaveAttribute('data-next-goal-verdict-state', 'disputed');
    await expect(node).toHaveTextContent(
      /Compass disputes it: docs\/e2e\/notes\.md was deleted at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}, after the verdict\. Compass’s own reading stands\./,
    );
    await expect(node.textContent).not.toContain('could not confirm');
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

/* The harness giving up on the goal is its own claim, published outside the goal because the goal is ended:
   worded as the harness's say-so, never as met, and it moves no level and counts as no check. */
const GAVE_UP_AT = 1_000;
const GAVE_UP_REASON = 'the path named in the goal does not exist';
const gaveUp = {
  session_goal: null,
  session_goal_gave_up: { at: GAVE_UP_AT, reason: GAVE_UP_REASON },
};

export const HarnessGaveUpOnTheGoal: Story = {
  ...scenario({ session: gaveUp }),
  play: async ({ canvasElement }) => {
    const node = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-goal-gave-up]');
      if (!found) throw new Error('no give-up note');
      return found;
    });
    await expect(node).toHaveTextContent(
      /The harness’s claim: Claude Code gave up on this goal at (\d{4}-\d{2}-\d{2} )?\d{1,2}:\d{2}\./,
    );
    await expect(node).toHaveTextContent(`Its reason: “${GAVE_UP_REASON}”`);
    // Not a verdict: never "met", never an invitation to analyze again, no level, no check.
    await expect(node.textContent).not.toMatch(/\bmet\b/);
    await expect(node.textContent).not.toContain('Analyze again');
    await expect(node.textContent).not.toMatch(/\b(Low|Medium|High)\b/);
    await expect(canvasElement.querySelector('[data-next-goal-verdict]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-drift-pill]')).toBeNull();
  },
};

export const HarnessGaveUpBesideAnAnalysisChangesNoLevel: Story = {
  ...scenario({
    session: { ...gaveUp, ...checked('agrees', 'written-before') },
    facts: FACTS,
    work: HIGH,
  }),
  play: async ({ canvasElement }) => {
    const node = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-goal-gave-up]');
      if (!found) throw new Error('no give-up note');
      return found;
    });
    await expect(node).toHaveTextContent('Compass has not checked it');
    await expect(node.textContent).not.toContain('Compass agrees');
    await expect(canvasElement.querySelector('[data-next-goal-verdict]')).toBeNull();
  },
};
