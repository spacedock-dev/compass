import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import {
  PiCheck,
  PiCheckBold,
  PiCheckCircle,
  PiCheckFat,
  PiChecks,
  PiCheckSquare,
} from 'react-icons/pi';
import {
  HARNESS_LIMIT,
  JOB_NOTE_SO_FAR,
  JOB_TITLE,
  LIVE_LEVEL_NAMES,
  NUDGE,
  RESULT_DEPARTS,
  UNCHECKED,
} from '../src/drift/sentences';
import { INTENT_EDITED } from '../src/intent/sentences';
import {
  analysisRow,
  DEPARTURE_READING,
  DriftScenario,
  failedCheck,
  fact,
  JOB,
  JOB_STEPS,
  passedCheck,
  STORED_READING,
  written,
  type Scenario,
} from './drift.scenario';
import { REASON_CASES, routeFor } from './drift.reasons';

/* The Intent and drift card, held by stage, by harness and by route. Each story mounts the real page over a
   scripted backend and asserts what a reader sees: the words the card prints and the controls it draws. The
   strings come from the page's own sentence tables where they are one string, and are spelt out where the
   page composes them from a count or a number. Every story asserts a retired string ("Looks right",
   "Send to session") absent, and a result also asserts `Done` and a check mark absent, because a result is an
   account of the evidence and never that the work was done.

   Controls and words are found by role and accessible name. Where the page gives a part no role or name, the
   story reads the `data-` hook the page already draws on it, never a class name, and the line says why.
   Every story mounts a running session with the press open, as the server publishes it. */

const meta = {
  title: 'Drift/Stages, harness limits and no reader',
  component: DriftScenario,
} satisfies Meta<typeof DriftScenario>;
export default meta;
type Story = StoryObj<typeof meta>;

const scenario = (value: Scenario): Pick<Story, 'args'> => ({ args: { scenario: value } });

/* The button the page draws as its one primary. `data-variant` has no accessible equivalent: weight is only
   visual, so this is the one way to count it. The count is over the whole page: the Raise control is the only
   other primary the page owns, and only for a session that is waiting on the reader. */
const primaries = (root: HTMLElement): HTMLElement[] => [
  ...root.querySelectorAll<HTMLElement>('[data-variant="primary"]'),
];

const button = (root: HTMLElement, name: string | RegExp) =>
  within(root).getByRole('button', { name });
const findButton = (root: HTMLElement, name: string | RegExp) =>
  within(root).findByRole('button', { name });

async function drawn(canvasElement: HTMLElement): Promise<HTMLElement> {
  return within(canvasElement).findByRole('region', { name: 'Drift' });
}

/* The controls load with the facts, after the card itself: a story waits for the one it asserts. */
const analyzeButton = (card: HTMLElement) => findButton(card, /^Analyze drift$/);
const steerBack = (card: HTMLElement) => findButton(card, 'Steer back');

/* A result's account of the work is never "done": no word for it and no mark. The mark is drawn by CSS on an
   empty span, so the words alone cannot show it: every pseudo-element's generated content is read, and no
   icon of the page's check family may sit in the result. */
const CHECK_GLYPHS = /[✓✔☑✅]/;

function checkIconPaths(): Set<string> {
  const host = document.createElement('div');
  const root = createRoot(host);
  const icons = [PiCheck, PiCheckBold, PiCheckCircle, PiCheckFat, PiChecks, PiCheckSquare];
  flushSync(() =>
    root.render(
      <>
        {icons.map((Glyph, index) => (
          <Glyph key={index} />
        ))}
      </>,
    ),
  );
  const paths = new Set(
    [...host.querySelectorAll('path')].map((path) => path.getAttribute('d') ?? ''),
  );
  root.unmount();
  paths.delete('');
  return paths;
}

async function noCheckMark(root: HTMLElement) {
  await expect(root.textContent).not.toMatch(CHECK_GLYPHS);
  const generated = [root, ...root.querySelectorAll<HTMLElement>('*')].flatMap((node) =>
    (['::before', '::after'] as const).map((pseudo) => getComputedStyle(node, pseudo).content),
  );
  await expect(generated.filter((content) => CHECK_GLYPHS.test(content))).toEqual([]);
  const checks = checkIconPaths();
  await expect(checks.size).toBeGreaterThan(0);
  const drawnChecks = [...root.querySelectorAll('svg path')].filter((path) =>
    checks.has(path.getAttribute('d') ?? ''),
  );
  await expect(drawnChecks).toEqual([]);
}

async function neverDone(root: HTMLElement) {
  await expect(root.textContent).not.toMatch(/\bDone\b/);
  await noCheckMark(root);
}

async function neverRetired(root: HTMLElement) {
  await expect(root.textContent).not.toContain('Looks right');
  await expect(root.textContent).not.toContain('Send to session');
}

/* A failed check counts for Steer back only after a message from the person, so each story that offers it
   carries one before the check. */
const FAILED = [failedCheck('c1', 500)];
const personSaid = (harness = 'claude') =>
  fact('u1', 200, { type: 'user_message', by: 'person:me', summary: 'Ship it' }, harness);
const PROMPT = personSaid();
const WRITES = [
  written('w1', 220, 'src/queue/worker.ts'),
  written('w2', 240, 'src/queue/index.ts'),
  written('w3', 260, 'tests/test_queue.py'),
];

/* Stage 1: no saved words. The first prompt is drafted into the goal box and marked as the prompt's, nothing
   is stored, and the press that reads it adopts it, so Analyze is the one primary. Save intent is live over
   the draft and stays quiet. */
export const IdleWithADraftedGoal: Story = {
  ...scenario({ unsaved: true }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const page = within(canvasElement);
    const goal = await page.findByRole('textbox', { name: 'Goal' });
    await expect(goal).toHaveValue('Ship the queue worker');
    await expect(await page.findByText(/^From your prompt · first · not saved\./)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save intent' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
    const analyze = await analyzeButton(card);
    await expect(analyze).not.toHaveAttribute('aria-disabled');
    await expect(within(card).queryByText(INTENT_EDITED)).toBeNull();
    await expect(primaries(canvasElement)).toEqual([analyze]);
    await neverRetired(canvasElement);
  },
};

/* The same stage once the reader edits the draft: Analyze would read words that are not saved, so it is
   refused with the step that lifts that. The refused control stays on the page in its primary weight, drawn
   hatched, so the one primary does not move while the words are saved. */
export const IdleWithAnEditedDraft: Story = {
  ...scenario({ unsaved: true }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const goal = await within(canvasElement).findByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ', then verify');
    await within(card).findByText(INTENT_EDITED);
    const analyze = button(card, /^Analyze drift$/);
    await expect(analyze).toHaveAttribute('aria-disabled', 'true');
    await expect(primaries(canvasElement)).toEqual([analyze]);
    await neverRetired(canvasElement);
  },
};

const LIVE_HIGH = {
  harness: 'claude',
  sid: 's1',
  level: 'high',
  revision: 3,
  computed_at: 990,
  reasons: ['failed-check'],
  cites: ['c1'],
  rose_at: '',
  rose_from: '',
};

/* Stage 2, and the Claude Code harness row: the live monitor is the reader's switch, off until pressed, and
   its level is from checks and file paths with no model. Claude Code is the one harness with the level, the
   switch and Steer back together. The level has no role or name, so it is read by its `data-` hook. */
export const LiveMonitorAtHigh: Story = {
  ...scenario({ facts: [PROMPT, ...FAILED], work: { live_levels: [LIVE_HIGH] } }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const page = within(canvasElement);
    const monitor = await page.findByRole('switch', { name: 'Live monitor' });
    await expect(monitor).toHaveAttribute('aria-checked', 'false');
    await expect(card.querySelector('[data-next-drift-level]')).toBeNull();
    await userEvent.click(monitor);
    const level = await waitFor(() => {
      const node = card.querySelector('[data-next-drift-level]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(level).toHaveTextContent(
      new RegExp(`^${LIVE_LEVEL_NAMES['high']}Live estimate · \\d\\d:\\d\\d`),
    );
    await within(level).findByRole('heading', { name: 'Recorded signals' });
    await expect(level).toHaveTextContent(/pytest -q failed .* ago at #\d+/);
    await expect(level).toHaveTextContent('Result time not recorded.');
    await expect(within(card).getByText(NUDGE)).toBeVisible();
    await expect(within(card).queryByText(HARNESS_LIMIT)).toBeNull();
    const analyze = await analyzeButton(card);
    await expect(await steerBack(card)).toBeVisible();
    await expect(primaries(canvasElement)).toEqual([analyze]);
    await neverRetired(canvasElement);
  },
};

/* Stage 3: the card says what is running, in the phases the server publishes, and stands Cancel where Analyze
   was, so no new press is offered. The steps are the producer's own words (`reading.PHASE_TEXT`), which
   `drift.reasons.test.ts` holds. A step's state is only a `data-state`, with `aria-current` on the active one. */
export const Analyzing: Story = {
  ...scenario({ facts: FAILED, payload: { reading_jobs: { 'claude:s1': JOB } } }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const box = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-analyzing]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(box).getByText(JOB_TITLE)).toBeVisible();
    const steps = within(box).getAllByRole('listitem');
    await expect(steps.map((step) => [step.textContent, step.getAttribute('data-state')])).toEqual([
      [JOB_STEPS[0]?.text, 'done'],
      [JOB_STEPS[1]?.text, 'active'],
      [JOB_STEPS[2]?.text, 'todo'],
    ]);
    await expect(steps[1]).toHaveAttribute('aria-current', 'step');
    await expect(within(box).getByText(JOB_NOTE_SO_FAR)).toBeVisible();
    await expect(button(card, 'Cancel')).toBeVisible();
    await expect(within(card).queryByRole('button', { name: /^Analyze/ })).toBeNull();
    await noCheckMark(box);
    // The running analysis is the card's state, not a press to make: nothing on the page asks for one.
    await expect(primaries(canvasElement)).toHaveLength(0);
    await neverRetired(canvasElement);
  },
};

const DEPARTURE_LEVEL = { analysis_levels: [analysisRow('claude')] };

/* Stage 4: a result under a departure carries its level and leads with Steer back, the one primary, and
   offers the intent as the other way out. The model's own words about the departure are drawn, and the work
   is grouped by folder. A result's rows have no role beyond list items, so their state is read from the
   `data-next-result-state` hook and the card's level from `data-next-drift-level`. */
export const ResultUnderADeparture: Story = {
  ...scenario({
    session: STORED_READING,
    facts: [...WRITES, ...FAILED, passedCheck('c2', 600)],
    work: DEPARTURE_LEVEL,
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const result = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-result]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    const level = await waitFor(() => {
      const node = card.querySelector('[data-next-drift-level]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(level).toHaveTextContent(new RegExp(`^${LIVE_LEVEL_NAMES['high']}Analysis`));
    await expect(level).toHaveTextContent(
      /Analysis at \d\d:\d\d · intent against cited checks and messages\./,
    );
    await expect(level).toHaveTextContent(/pytest -q failed .* at #\d+/);
    await expect(level).not.toHaveTextContent('Live estimate');
    await within(result).findByRole('heading', { name: new RegExp(`^${RESULT_DEPARTS}`) });
    await expect(
      within(result).getByRole('heading', { name: new RegExp(`^${RESULT_DEPARTS}`) }),
    ).toHaveTextContent('1 departure');
    await expect(within(result).getByText(DEPARTURE_READING.criteria.goal.detail)).toBeVisible();
    const goal = result.querySelector('[data-next-result-goal]') as HTMLElement;
    await expect(goal).toHaveAttribute('data-next-result-state', 'departs');
    const line = within(result)
      .getAllByRole('listitem')
      .find((item) => item.textContent?.includes('Tests pass')) as HTMLElement;
    await expect(line).toHaveAttribute('data-next-result-state', 'consistent');
    await expect(line).toHaveTextContent(/Consistent with #\d+/);
    await expect(
      within(result).getByRole('heading', { name: 'Where the work went' }),
    ).toBeVisible();
    await expect(within(result).getByText(/src\/queue/)).toBeVisible();
    const steer = await steerBack(card);
    await expect(button(card, 'Update intent instead')).toBeVisible();
    await expect(primaries(canvasElement)).toEqual([steer]);
    // A current result draws no second run control; Analyze returns when the reading is out of date.
    await expect(within(card).queryByRole('button', { name: /^Analyze/ })).toBeNull();
    await neverDone(result);
    await neverRetired(canvasElement);
  },
};

/* Stage 5: work that arrived after the reading says so, and the one press that reads it again stands in the
   callout, with nowhere else on the card to start another. The callout is a card with no role, read by its
   `data-next-result-stale` hook. */
export const StaleResult: Story = {
  ...scenario({
    session: STORED_READING,
    facts: [
      ...WRITES,
      ...FAILED,
      passedCheck('c2', 600),
      passedCheck('c3', 1200),
      fact('m1', 1250, { type: 'agent_message', by: 'agent' }),
    ],
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const stale = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-result-stale="work"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(within(stale).getByText('New work since this analysis.')).toBeVisible();
    const again = within(stale).getByRole('button', { name: 'Analyze again' });
    await expect(within(card).getAllByRole('button', { name: /^Analyze/ })).toEqual([again]);
    // Said inside the reading's folded account, so it is in the page and not in view.
    await expect(
      within(card).getByText('1 check, 1 message arrived since this analysis.'),
    ).toBeInTheDocument();
    // The departure still stands, so Steer back stays the one primary and Analyze again is the quiet way to
    // read the new work.
    await expect(primaries(canvasElement)).toEqual([await steerBack(card)]);
    await neverDone(card);
    await neverRetired(canvasElement);
  },
};

/* No reader on this machine (stage 6). The reason stands where Analyze would be and no inert Analyze is
   drawn, because there is no press to refuse. With a failed check on the record, Steer back is the one
   primary: it is the only thing the page can still offer. */
async function noReaderStory(canvasElement: HTMLElement, card: HTMLElement, reason: string) {
  const note = REASON_CASES[reason]?.note as string;
  await expect(await within(card).findByText(note)).toBeVisible();
  await expect(within(card).queryByRole('button', { name: /^Analyze/ })).toBeNull();
  await expect(card).not.toHaveTextContent('Analyze drift');
  const steer = await steerBack(card);
  await expect(primaries(canvasElement)).toEqual([steer]);
  await neverRetired(canvasElement);
}

/* One story per reason the producer can give a route, built by `routeStory`. `drift.reasons.test.ts` reads the
   reasons off the exported stories themselves, so one that is removed or commented out fails there. A reason
   with no reader draws its sentence where Analyze would be (stage 6 is the first of these). A reason with a
   reader draws Analyze, and says why this reader in "What is sent". */
function routeStory(reason: string): Story {
  const found = REASON_CASES[reason];
  if (!found) throw new Error(`no story fixture for route reason ${reason}`);
  const harness = found.harness;
  const checks = [personSaid(harness), failedCheck('c1', 500, harness)];
  return {
    ...scenario({ harness, facts: checks, route: routeFor(reason) }),
    play: async ({ canvasElement }) => {
      const card = await drawn(canvasElement);
      if (!found.provider) {
        await noReaderStory(canvasElement, card, reason);
        return;
      }
      const analyze = await analyzeButton(card);
      await expect(within(card).queryByText(found.note)).toBeNull();
      await userEvent.click(
        button(card, found.fallback ? `What is sent to ${found.label}` : 'What is sent'),
      );
      // The popover is drawn outside the card, in its own dialog.
      const sentTo = await within(document.body).findByRole('dialog');
      // The popover fades in, so its words are in the dialog before they are in view.
      await waitFor(() =>
        expect(within(sentTo).getByText(found.note, { exact: false })).toBeVisible(),
      );
      await expect(primaries(canvasElement)).toEqual([analyze]);
      await neverRetired(canvasElement);
    },
  };
}

export const OwnHarnessReads: Story = routeStory('own-harness');
export const HarnessWithNoProducerIsReadByCodex: Story = routeStory('no-own-producer');
export const ClaudeCodeMissingFallsBackToCodex: Story = routeStory('fallback-not-installed');
export const ClaudeCodeUnqualifiedFallsBackToCodex: Story = routeStory('fallback-not-qualified');
export const NoReaderNeitherInstalled: Story = routeStory('not-installed');
export const NoReaderClaudeMissingCodexUnqualified: Story = routeStory(
  'not-installed-other-not-qualified',
);
export const NoReaderClaudeUnqualifiedCodexMissing: Story = routeStory(
  'not-qualified-other-not-installed',
);
export const NoReaderNeitherQualified: Story = routeStory('not-qualified');

/* Harness limits. Compass reads work results from Claude Code and Pi only, the live estimate from Claude
   Code only, and corrections for Claude Code only; a card for any other harness says so and draws no level,
   because a level from work it cannot read would measure nothing. Claude Code's own row is the live monitor
   story above. */

/* Pi has work results and so a level, but only from an analysis: there is no live estimate to switch on, and
   no correction to steer back with. */
export const PiShowsAnalysisLevelWithNoSwitchAndNoSteerBack: Story = {
  ...scenario({
    harness: 'pi',
    session: STORED_READING,
    facts: [...WRITES, failedCheck('c1', 500, 'pi'), passedCheck('c2', 600, 'pi')],
    work: { analysis_levels: [analysisRow('pi')] },
  }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    const level = await waitFor(() => {
      const node = card.querySelector('[data-next-drift-level]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(level).toHaveTextContent(new RegExp(`^${LIVE_LEVEL_NAMES['high']}Analysis`));
    await expect(within(canvasElement).queryByRole('switch')).toBeNull();
    await expect(within(card).queryByRole('button', { name: 'Steer back' })).toBeNull();
    await expect(within(card).queryByText(HARNESS_LIMIT)).toBeNull();
    await expect(card).not.toHaveTextContent('Live estimate');
    // A current result draws no run control and Pi has nothing to steer with, so no control is primary.
    await expect(primaries(canvasElement)).toHaveLength(0);
    await neverRetired(canvasElement);
  },
};

/* Codex and Antigravity: the sentence in place of a level, and neither a meter nor a switch. Analyze is still
   offered, because a reading needs the saved words and the messages, not work results. The meter and its
   scale are decorative and hidden from assistive tech, so their absence is read from their words. */
const limited = (harness: 'codex' | 'antigravity'): Story => ({
  ...scenario({ harness, facts: [personSaid(harness), failedCheck('c1', 500, harness)] }),
  play: async ({ canvasElement }) => {
    const card = await drawn(canvasElement);
    await expect(await within(card).findByText(HARNESS_LIMIT)).toBeVisible();
    await expect(card.querySelector('[data-next-drift-level]')).toBeNull();
    for (const word of [...Object.values(LIVE_LEVEL_NAMES), UNCHECKED]) {
      await expect(within(card).queryByText(word)).toBeNull();
    }
    await expect(within(canvasElement).queryByRole('switch')).toBeNull();
    await expect(within(card).queryByRole('button', { name: 'Steer back' })).toBeNull();
    const analyze = await analyzeButton(card);
    await expect(primaries(canvasElement)).toEqual([analyze]);
    await neverRetired(canvasElement);
  },
});

export const CodexSaysItCannotReadWork: Story = limited('codex');
export const AntigravitySaysItCannotReadWork: Story = limited('antigravity');
