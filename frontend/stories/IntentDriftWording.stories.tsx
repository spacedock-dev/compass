import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createShell } from '../src/shell/createShell';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* The words a reader meets at the edges of a reading: why a line reads "Can't tell", what the how-to says a
   reading can settle and how far to trust it, and what saving an intent on an ended session still cannot do.
   One whole page over a scripted backend, so each assertion reads what the reader reads. */

const ROUTE = {
  provider: 'claude',
  harness: 'claude',
  destination: 'api',
  words_destination: 'api',
  label: 'Claude Code',
  model: 'm',
  disclosure: 'This sends the session to Claude Code.',
  disclosure_parts: ['Your saved words.', 'The agent messages.'],
  tool_output: 'Tool output goes to the api.',
};

const fact = (id: string, at: number, extra: Record<string, unknown> = {}) => ({
  fact_id: id,
  type: 'tool_report',
  by: 'agent',
  summary: `Entry ${id}`,
  at,
  source_session: { harness: 'claude', sid: 's1' },
  evidence: { source: 'transcript', confidence: 'exact' },
  ...extra,
});

/* A verdict the reading withdrew: the published cites are emptied whenever one is, so the page cannot tell
   a check that does not show the line from a write that was cited in its place, or nothing. */
const withdrawn = (cites: string[]) => ({
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
  cutoff: 'Evidence read to its end.',
  coverage: {
    tail_truncated: false,
    tail_start: null,
    unlisted: 0,
    unread_checks: 0,
    goal_source: 'typed',
  },
  criteria: {
    goal: {
      result: 'not verifiable from available evidence',
      cites,
      detail: '',
      clause: 'Ship the queue',
      why: 'check-does-not-show-it',
    },
  },
});

function WordingExample({
  cites,
  ended = false,
}: {
  readonly cites?: readonly string[];
  readonly ended?: boolean;
}) {
  const [shell] = useState(() => {
    const clock = createFakeClock();
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    let generation = 1000;
    let goal = cites ? 'Ship the queue' : '';
    let revision = cites ? 3 : 0;
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url.startsWith('/api/data'))
          return json({
            generated: generation++,
            annotate: true,
            annotate_cap: 240,
            reading_check: 'passed',
            reading: {
              providers: { claude: true },
              words: { claude: true },
              tool_output: { claude: ['api'] },
              used: 1,
              limit: 10,
            },
            reading_routes: { claude: ROUTE },
            sessions: [
              {
                harness: 'claude',
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic session',
                state: 'idle',
                first_prompt: 'Ship the queue worker',
                first_prompt_at: 100,
                turn_end_at: 990,
                ...(ended ? { ended_at: 995 } : {}),
                annotation_goal: goal,
                annotation_revision: revision,
                annotation_revision_count: revision ? 1 : 0,
                annotation_at: revision ? 990 : null,
                annotation_goal_saved_at: revision ? 990 : null,
                annotation_window_start: 100,
                ...(cites
                  ? {
                      annotation_line_1: 'Tests pass',
                      annotation_assessment: withdrawn([...cites]),
                      annotation_reading_count: 1,
                    }
                  : {}),
              },
            ],
          });
        if (url.startsWith('/api/project-context'))
          return json({
            semantic: {
              facts: [
                fact('c1', 500, {
                  subject: 'check',
                  result: 'failed',
                  result_source: 'failed flag',
                  summary: 'pytest -q',
                }),
                fact('w1', 550, { subject: 'write', summary: 'src/queue.ts' }),
              ],
            },
            sources: { work: { tool_reports: [] } },
          });
        if (url.startsWith('/api/session-record'))
          return json({ state: 'ok', entries: [], next: null, reached_start: true });
        if (url === '/api/annotate') {
          const body = JSON.parse(String(init?.body)) as { goal?: string };
          goal = body.goal ?? goal;
          revision += 1;
          return json({
            ok: true,
            outcome: 'stored',
            persisted: true,
            revision,
            saved_revision: revision,
            revision_count: 1,
          });
        }
        if (url.startsWith('/api/annotations'))
          return json({ annotations: [], intent_revision: 'r1' });
        return json({});
      },
    });
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return <App shell={shell} />;
}

const meta = {
  title: 'Intent/Wording at the edges of a reading',
  component: WordingExample,
} satisfies Meta<typeof WordingExample>;
export default meta;
type Story = StoryObj<typeof meta>;

const REASON =
  'What it cited does not show this: a departure needs its latest run failing, and a consistent its latest run passing with no change after it, both after the words you saved.';

async function evidenceOf(canvasElement: HTMLElement) {
  await waitFor(() =>
    expect(canvasElement.querySelector('[data-next-drift-verdict]')).toHaveTextContent(
      "Can't tell",
    ),
  );
  const goal = canvasElement.querySelector('[data-next-result-goal]') as HTMLElement;
  // The reason is in view under the line; no Evidence fold holds it (owner, 2026-10-23).
  await expect(within(goal).queryByRole('button', { name: /^(Evidence|Source)/ })).toBeNull();
  return goal;
}

export const CantTellWithNothingPublishedAsCited: Story = {
  args: { cites: [] },
  play: async ({ canvasElement }) => {
    const goal = await evidenceOf(canvasElement);
    await waitFor(() => expect(goal).toHaveTextContent(REASON));
    await expect(goal).not.toHaveTextContent('The check it cited');
  },
};

export const CantTellAfterAWriteWasCited: Story = {
  args: { cites: ['w1'] },
  play: async ({ canvasElement }) => {
    const goal = await evidenceOf(canvasElement);
    await waitFor(() => expect(goal).toHaveTextContent(REASON));
    await expect(goal).not.toHaveTextContent('The check it cited');
  },
};

export const HowToSaysWhatAReadingCanSettleAndHowFarToTrustIt: Story = {
  args: { cites: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'More about these words' }));
    await userEvent.click(
      await canvas.findByRole('button', { name: 'How Intent and drift works' }),
    );
    const popup = await within(document.body).findByRole('dialog', {
      name: 'How Intent and drift works',
    });
    const settle = popup.querySelector('[data-next-intent-howto-settle]') as HTMLElement;
    await expect(settle).toHaveTextContent("Readings settle a command's latest unpiped run");
    await expect(settle).toHaveTextContent('nothing written after it');
    await expect(settle).toHaveTextContent('A recorded write breaking a folder limit also departs');
    await expect(popup.querySelector('[data-next-intent-howto-accuracy]')).toHaveTextContent(
      "The Claude reader's accuracy check has not passed, and its latest correction is unmeasured, so read a level as an account of the evidence, not a measurement.",
    );
  },
};

async function saveTyped(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  const goal = await canvas.findByRole('textbox', { name: 'Goal' });
  await userEvent.clear(goal);
  await userEvent.type(goal, 'Land the worker behind a flag');
  await userEvent.click(canvas.getByRole('button', { name: 'Save intent' }));
  const footer = canvasElement.querySelector('.next-cockpit-held-footer') as HTMLElement;
  await waitFor(() => expect(footer).toHaveTextContent('Saved.'));
  return footer;
}

export const SavingOnAnEndedSessionRepeatsTheCaveat: Story = {
  args: { ended: true },
  play: async ({ canvasElement }) => {
    const footer = await saveTyped(canvasElement);
    await expect(footer.querySelector('.next-cockpit-held-cue')).toHaveTextContent(
      'Saved. This session has ended. What you save now is kept, but Analyze will not check the session against it. Analyze still uses the intent you saved before the session ended, or a goal taken from one of your prompts.',
    );
  },
};

export const SavingOnALiveSessionSaysOnlyThatItSaved: Story = {
  play: async ({ canvasElement }) => {
    const footer = await saveTyped(canvasElement);
    await expect(footer.querySelector('.next-cockpit-held-cue')).toHaveTextContent(/^Saved\.$/);
  },
};
