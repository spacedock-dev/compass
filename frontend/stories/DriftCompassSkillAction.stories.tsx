import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import published from '../test/fixtures/compass-skill-action.json';
import { DEPARTURE_READING, DriftScenario, fact, type Scenario } from './drift.scenario';
import { OutlinePage } from './outline.scenario';

/* The reader typed `/compass:compass sessions` inside the session, after saving their goal. The agent ran Compass
   and repeated what it printed. That asked Compass a question: it is not a message the reader sent the session,
   so the Drift card asks nothing about it, and the outline opens no phase for it. Full activity still lists what
   the agent ran and said, because it happened.

   The facts and the outline are not written here. They are what the server published for a transcript in
   Claude Code's recorded shapes (`test_compass_skill_action`, `TheStoryReadsWhatTheServerPublishesTest`, which
   fails when the committed file is not what the server now publishes). A server that again publishes the
   command as the reader's message changes the file, and these stories assert against the change. Only the times
   are the scenario's: before the save for the reader's work, after it for Compass's turn. */

const meta = {
  title: 'Drift/A Compass skill action',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

type Published = (typeof published.facts)[number];

const FIRST = 'Add retry with backoff to the webhook handler.';
const COMMAND = '/compass:compass';
const ECHOED = 'ECHOED-BY-AGENT placeholder board line for another session';

/* The server's facts in its own order of time, placed in the scenario's session: the reader's three entries
   before the save at 990, everything after them inside the Compass turn. */
const ordered = [...published.facts].sort((a, b) => a.at - b.at);
const TIMES = [200, 300, 400, 1050, 1100, 1150, 1200];
const placed = ordered.map(({ source_session: _own, ...fields }: Published, index) => {
  const at = TIMES[index] ?? 1200 + index;
  // A check's result time moves with its call, or the recorded one would land after every reading here.
  return fact(fields.fact_id, at, {
    ...fields,
    at,
    ...('result_at' in fields ? { result_at: at + 5 } : {}),
  });
});
const CHECK = ordered.find((row) => row.type === 'tool_report' && row.subject === 'check');
const ECHO = ordered.find((row) => row.summary === ECHOED);
const RAN = ordered.find((row) => row.subject === 'command');

const reading = {
  ...DEPARTURE_READING,
  read_at: 1300,
  evidence_through: 1300,
  criteria: {
    goal: {
      result: 'consistent with the evidence read',
      cites: [CHECK?.fact_id ?? ''],
      detail: '',
      clause: 'Ship the queue',
    },
    line_1: {
      result: 'consistent with the evidence read',
      cites: [CHECK?.fact_id ?? ''],
      detail: '',
      clause: 'Tests pass',
    },
  },
};

/* The same reading, made before the reader typed the Compass command: the turn comes after it. */
const earlier = { ...reading, read_at: 1000, evidence_through: 1000 };

const scenario = (facts: readonly unknown[]): Scenario => ({
  session: { annotation_assessment: reading, annotation_reading_count: 1 },
  facts,
});

const scenarioAfter = (facts: readonly unknown[]): Scenario => ({
  session: { annotation_assessment: earlier, annotation_reading_count: 1 },
  facts,
});

const driftOf = async (canvasElement: HTMLElement) => {
  const drift = await within(canvasElement).findByRole('region', { name: 'Drift' });
  await waitFor(() => expect(drift.querySelector('[data-next-result]')).not.toBeNull());
  return drift;
};

export const ACompassSkillActionAddsNothingToTheGoal: Story = {
  args: { scenario: scenario(placed) },
  play: async ({ canvasElement }) => {
    const drift = await driftOf(canvasElement);
    // The server published no message for the command, so nothing asks to add it.
    await expect(published.facts.map((row) => row.summary)).not.toContain(`${COMMAND} sessions`);
    await expect(drift).not.toHaveTextContent(/message adds:/);
    await expect(drift).not.toHaveTextContent(/messages after your goal/);
    await expect(drift.querySelector('[data-next-cockpit-direction-question]')).toBeNull();
    // Full activity still lists what the agent repeated, as the agent's.
    const echo = await waitFor(() => {
      const node = document.querySelector<HTMLElement>(
        `[data-next-entry-id="${ECHO?.fact_id ?? ''}"]`,
      );
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(echo.textContent).toContain(ECHOED);
    for (const row of document.querySelectorAll<HTMLElement>('[data-next-entry-id]'))
      await expect(row.textContent).not.toContain(COMMAND);
  },
};

/* The reading came before the command, so the turn lands after it. Nothing a reading reads changed, so the card
   stays current: no "New work since this analysis.", and no count of what arrived. */
export const ACompassSkillActionAfterAnAnalysisLeavesItCurrent: Story = {
  args: { scenario: scenarioAfter(placed) },
  play: async ({ canvasElement }) => {
    const drift = await driftOf(canvasElement);
    await expect(drift).not.toHaveTextContent(/New work since this analysis/);
    await expect(drift).not.toHaveTextContent(/arrived since this analysis/);
    await expect(drift.querySelector('[data-next-result-stale]')).toBeNull();
  },
};

/* The control: the same facts without the server's mark, so the absence above is the mark's doing and not a card
   that never says it. */
export const TheSameTurnWithoutTheMarkIsNewWork: Story = {
  args: {
    scenario: scenarioAfter(
      placed.map(({ compass_turn: _marked, ...rest }: Record<string, unknown>) => rest),
    ),
  },
  play: async ({ canvasElement }) => {
    const drift = await driftOf(canvasElement);
    await expect(drift).toHaveTextContent(/New work since this analysis/);
    await expect(drift).toHaveTextContent(/arrived since this analysis/);
  },
};

/* Full activity says whose answer the agent's echo and the command it ran are, and says nothing of the reader's own
   work. */
export const FullActivityLabelsTheEntriesAsCompassAnswer: Story = {
  args: { scenario: scenario(placed) },
  play: async ({ canvasElement }) => {
    await driftOf(canvasElement);
    const labelled = async (id: string | undefined) => {
      const row = await waitFor(() => {
        const node = document.querySelector<HTMLElement>(`[data-next-entry-id="${id ?? ''}"]`);
        expect(node).not.toBeNull();
        return node as HTMLElement;
      });
      return row.querySelector('[data-next-entry-flag="compass"]');
    };
    const echoFlag = await labelled(ECHO?.fact_id);
    await expect(echoFlag).toHaveTextContent('Compass’s answer, not read');
    await expect(await labelled(RAN?.fact_id)).toHaveTextContent('Compass’s answer, not read');
    await expect(await labelled(CHECK?.fact_id)).toBeNull();
    await expect(document.querySelectorAll('[data-next-entry-flag="compass"]')).toHaveLength(2);
    // The summary line counts the numbered entries, as it counts every other kind, and the command the agent
    // ran is listed without a number, so it is labelled and not counted there.
    const numbered = document.querySelectorAll('[data-next-entry][data-next-entry-id]');
    const numberedLabels = [...numbered].filter((row) =>
      row.querySelector('[data-next-entry-flag="compass"]'),
    ).length;
    await expect(numberedLabels).toBe(1);
    await expect(document.querySelector('.next-cockpit-work-mix')).toHaveTextContent(
      new RegExp(`${String(numberedLabels)} marked as Compass’s answer`),
    );
  },
};

/* The control: the same record with a message the reader typed after the save is asked about, so the absence
   above is the server's doing and not a page that never asks. */
export const AMessageTheReaderTypedAfterTheGoalIsStillAskedAbout: Story = {
  args: {
    scenario: scenario([
      ...placed,
      fact('typed-later', 1250, {
        type: 'user_message',
        by: 'person:me',
        summary: 'Also cover the retry path with a test.',
      }),
    ]),
  },
  play: async ({ canvasElement }) => {
    const drift = await driftOf(canvasElement);
    await expect(await within(drift).findByText(/message adds:/)).toBeVisible();
  },
};

/* The outline the server made for the same transcript: one phase, the reader's, holding their check and the
   agent's one reply. The command opens none, and what the agent repeated is not in the phase. */
export const TheOutlineOpensNoPhaseForACompassSkillAction: Story = {
  // The meta's component takes a scenario; this story draws the outline card over its own backend instead.
  args: { scenario: scenario(placed) },
  render: () => <OutlinePage outline={published.outline} />,
  play: async ({ canvasElement }) => {
    const region = await within(canvasElement).findByRole('region', {
      name: 'What the session has done',
    });
    const blocks = await waitFor(() => {
      const found = region.querySelectorAll<HTMLElement>('[data-next-outline-block]');
      expect(found).toHaveLength(1);
      return found;
    });
    const [only] = [...blocks] as [HTMLElement];
    await expect(within(only).getByText(FIRST)).toBeVisible();
    await expect(region).not.toHaveTextContent(COMMAND);
    await expect(only.querySelector('[data-next-outline-counts]')).toHaveTextContent(
      /replied 1 time/,
    );
  },
};
