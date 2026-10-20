import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { clock } from '../src/observed/values';
import { readerUtcOffset } from '../src/drift/correction';
import {
  PRESS_CODEX,
  SCOPE_TEXT_IDLE,
  STEER_OFF_MARKED,
  STEER_OFF_OLDER,
  WHY_OFF,
} from '../src/drift/sentences';
import { DEPARTURE_READING, DriftScenario, fact, type Scenario } from './drift.scenario';

/* The usability review's rulings of 2026-10-20 (owner): an idle Claude Code session whose last turn has no
   recorded finish can be analyzed and says how far it read; a refused Analyze says its true condition and a
   press shows why; Steer back stays beside the departures, labelled with the check's time, and says why where
   the rules withhold it; a failed analysis names its cause; the correction is drawn in the reader's zone. */

const meta = {
  title: 'Drift/Idle analysis and Steer back',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

/* An idle Claude Code session with no recorded turn finish, as the collector publishes it. */
const IDLE = {
  state: 'idle',
  state_detail: 'last turn not recorded as finished',
  turn_end_at: null,
  finished_at: null,
};
const SAID = fact('m1', 600, {
  type: 'agent_message',
  by: 'agent',
  summary: 'Done: the billing rate is now 0.25.',
});
const departsAtMessage = {
  goal: {
    result: 'departure',
    cites: ['m1'],
    detail: 'The agent edited billing instead.',
    clause: 'Ship the queue',
  },
};
const IDLE_READING = {
  ...DEPARTURE_READING,
  scope: 'mid-flight',
  scope_text: SCOPE_TEXT_IDLE,
  evidence_through: 900,
  criteria: departsAtMessage,
};

export const AnalyzeOpensOnAnIdleSessionWithNoRecordedFinish: Story = {
  ...scenario({ session: IDLE }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const analyze = await canvas.findByRole('button', { name: 'Analyze drift' });
    await expect(analyze).not.toHaveAttribute('aria-disabled');
    await expect(canvasElement.textContent).not.toContain('Analyze opens while this session runs.');
    await expect(canvasElement.textContent).not.toContain(WHY_OFF);
  },
};

export const AnIdleReadingSaysHowFarItRead: Story = {
  ...scenario({
    session: { ...IDLE, annotation_assessment: IDLE_READING, annotation_reading_count: 1 },
    facts: [SAID],
  }),
  play: async ({ canvasElement }) => {
    const line = await waitFor(() => {
      const node = canvasElement.querySelector('[data-next-reading-idle]');
      if (!node) throw new Error('no idle line');
      return node;
    });
    await expect(line).toHaveTextContent(
      `Read up to the last recorded entry at ${clock(900)}; the last turn was not recorded as finished.`,
    );
    await expect(canvasElement.querySelector('[data-next-result-heading]')).toHaveTextContent(
      /^So far:/,
    );
  },
};

/* Each refusal the board can still publish says the condition that holds, and a press reveals the server's
   whole sentence under Why Analyze is off. */
function refusal(
  harness: NonNullable<Scenario['harness']>,
  reason: string,
  line: string,
  extra: Record<string, unknown> = {},
): Story {
  const sentence = `The server's own account of ${reason}.`;
  return {
    ...scenario({
      harness,
      session: {
        state: 'idle',
        reading_eligibility: { ok: false, reason, until: null, sentence },
        ...extra,
      },
    }),
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      const analyze = await canvas.findByRole('button', { name: 'Analyze drift' });
      await expect(analyze).toHaveAttribute('aria-disabled', 'true');
      await expect(await canvas.findByText(line)).toBeVisible();
      await expect(canvas.getByText(sentence)).not.toBeVisible();
      await userEvent.click(analyze);
      await waitFor(() => expect(canvas.getByText(sentence)).toBeVisible());
      await expect(canvas.getByText(WHY_OFF)).toBeVisible();
    },
  };
}

export const RefusedCodexBetweenTurns = refusal('codex', 'idle-unknown', PRESS_CODEX);
export const RefusedTurnStopElsewhere = refusal(
  'antigravity',
  'turn-stop',
  'Analyze opens while a turn runs or once the session ends.',
);
export const RefusedUnobservable = refusal(
  'antigravity',
  'unobservable',
  'This harness sends no events, so Analyze opens only while it runs.',
);
export const RefusedIntentAfterEnd = refusal(
  'claude',
  'revision-after-end',
  'Your intent was saved after this session ended.',
  { ended_at: 950 },
);

const correctionPosts: Record<string, unknown>[] = [];
const LOCAL = clock(600);

export const SteerBackFromAnIdleSession: Story = {
  ...scenario({
    session: { ...IDLE, annotation_assessment: IDLE_READING, annotation_reading_count: 1 },
    facts: [SAID],
    correctionPosts,
    /* What `correction.compose` answers for the reader's zone: local time, the agent's own words, and no
       Compass entry number (the placeholder is drawn as nothing). */
    correction: {
      ok: true,
      parts: [
        `Back to my goal: Ship the queue\nThe session departed from my goal at ${LOCAL}`,
        { entry: 'm1' },
        ', where you said "Done: the billing rate is now 0.25".\nPlease continue from here.',
      ],
    },
  }),
  play: async ({ canvasElement }) => {
    correctionPosts.length = 0;
    const canvas = within(canvasElement);
    const steer = await canvas.findByRole('button', { name: 'Steer back' });
    await expect(await canvas.findByText(`from the check at ${clock(1000)}`)).toBeVisible();
    await userEvent.click(steer);
    const box = (await canvas.findByLabelText('Correction to copy')) as HTMLTextAreaElement;
    await expect(box.value).toContain(
      `The session departed from my goal at ${LOCAL}, where you said`,
    );
    await expect(box.value).not.toContain('activity list');
    await expect(box.value).not.toMatch(/#\d/);
    await expect(correctionPosts.at(-1)).toMatchObject({ utc_offset_minutes: readerUtcOffset() });
    await expect(canvas.getByText(/Compass never sends this/)).toBeVisible();
  },
};

export const SteerBackOffWhenMarkedInaccurate: Story = {
  ...scenario({
    session: {
      ...IDLE,
      annotation_assessment: IDLE_READING,
      annotation_reading_count: 1,
      annotation_not_accurate: true,
    },
    facts: [SAID],
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(STEER_OFF_MARKED)).toBeVisible();
    await expect(canvas.queryByRole('button', { name: 'Steer back' })).toBeNull();
  },
};

export const SteerBackOffForAnEarlierIntent: Story = {
  ...scenario({
    session: {
      ...IDLE,
      annotation_assessment: IDLE_READING,
      annotation_reading_count: 1,
      annotation_revision: 4,
    },
    facts: [SAID],
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(STEER_OFF_OLDER)).toBeVisible();
    await expect(canvas.queryByRole('button', { name: 'Steer back' })).toBeNull();
  },
};

/* The server's sentence for a Claude Code call that reported it is signed out
   (`reading.WITHHELD_CLAUDE_LOGIN`), stored as the last analysis's outcome. */
const LOGIN =
  'Analyze failed: Claude Code said it is not logged in. Nothing was saved. Fix that, then press Analyze drift again.';

export const AFailedAnalysisNamesItsCause: Story = {
  ...scenario({
    session: {
      ...IDLE,
      annotation_reading_withheld: LOGIN,
      annotation_reading_withheld_at: 995,
      annotation_reading_count: 1,
    },
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(new RegExp(`^Last analysis.*${LOGIN}$`))).toBeVisible();
    await expect(canvasElement.textContent).not.toContain('a fresh press is the only retry');
    await expect(canvas.getByRole('button', { name: 'Analyze drift' })).not.toHaveAttribute(
      'aria-disabled',
    );
  },
};
