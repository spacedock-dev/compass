import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { FIND_GOAL_NOTHING } from '../src/intent/sentences';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* "Find goal": the button beside the prompt list, the goal it finds with the prompts it quotes, and the answer when
   it finds nothing. Every request is counted, because the whole of the feature is that one press sends one and
   nothing else sends any. */

const SESSION_ROUTE = '#n=session:alpha%2Fapp:claude:s1';
const GOAL =
  'The upload client retries a dropped connection and resumes the upload, with the existing tests passing.';
const FIRST = 'Please add a retry to the upload client so a dropped connection resumes.';
const SECOND = 'Also make sure the existing tests still pass.';

const person = (id: string, at: number, ordinal: number, summary: string) => ({
  fact_id: id,
  type: 'user_message',
  by: 'person:me',
  summary,
  at,
  ordinal,
  source_session: { harness: 'claude', sid: 's1' },
  evidence: { source: 'transcript', confidence: 'exact' },
});

const FACTS = [
  person('f1', 1_760_000_100, 1, FIRST),
  {
    fact_id: 'a1',
    type: 'agent_message',
    by: 'agent',
    summary: 'Added the retry.',
    at: 1_760_000_200,
    ordinal: 2,
    source_session: { harness: 'claude', sid: 's1' },
    evidence: { source: 'transcript', confidence: 'exact' },
  },
  person('f2', 1_760_000_300, 3, SECOND),
];

const FOUND = {
  ok: true,
  produced: true,
  why: '',
  found: {
    goal: GOAL,
    found_at: 1_760_000_900,
    cites: [
      {
        fact_id: 'f1',
        ordinal: 1,
        at: 1_760_000_100,
        quotes: ['add a retry to the upload client', 'resume where it stopped'],
      },
      { fact_id: 'f2', ordinal: 3, at: 1_760_000_300, quotes: ['make sure the existing tests'] },
    ],
  },
  route: {
    provider: 'claude',
    label: 'Claude Code',
    model: 'm',
    harness: 'claude',
    vendor: 'Anthropic',
  },
};
const NOTHING = { ok: true, produced: false, found: null, why: 'none', route: FOUND.route };

const ROUTE = {
  provider: 'claude',
  harness: 'claude',
  destination: '',
  words_destination: 'api',
  label: 'Claude Code',
  model: 'm',
  disclosure: 'This sends your prompts to Claude Code.',
  disclosure_parts: ['Your prompts.'],
  tool_output: '',
};
const POLICY = {
  consent: true,
  off: false,
  reason: '',
  providers: { claude: true },
  words: { claude: true },
  tool_output: { claude: [] },
  used: 1,
  limit: 100,
};

interface Setup {
  readonly session?: Record<string, unknown>;
  readonly policy?: Record<string, unknown>;
  readonly find?: () => Response | Promise<Response>;
}

declare global {
  interface Window {
    __findRequests?: { path: string; body: unknown }[];
  }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function Harness({ setup }: { readonly setup?: Setup }) {
  const [shell] = useState(() => {
    const clock = createFakeClock();
    const history = fakeRouterEnvironment(SESSION_ROUTE);
    window.__findRequests = [];
    let saved = false;
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (init?.method === 'POST') {
          window.__findRequests?.push({
            path: url,
            body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
          });
        }
        if (url.startsWith('/api/data')) {
          return json({
            generated: 1_760_001_000,
            annotate: true,
            annotate_cap: 240,
            reading_check: 'passed',
            intent_revision: 'r1',
            reading: { ...POLICY, ...(setup?.policy ?? {}) },
            reading_routes: { claude: ROUTE },
            projects: [
              { project: 'alpha/app', project_key: '/repo/alpha', sessions: ['claude:s1'] },
            ],
            sessions: [
              {
                harness: 'claude',
                sid: 's1',
                project: 'alpha/app',
                project_key: '/repo/alpha',
                title: 'Upload retry',
                state: 'idle',
                started_at: 1_760_000_000,
                last_event_at: 1_760_000_900,
                first_prompt: FIRST,
                first_prompt_at: 1_760_000_100,
                latest_prompt: SECOND,
                latest_prompt_at: 1_760_000_300,
                annotation_goal: saved ? GOAL : '',
                annotation_goal_why: saved ? '' : 'No goal typed for this session.',
                annotation_lines_why: 'No expected outcome typed.',
                annotation_revision: saved ? 1 : 0,
                annotation_revision_count: saved ? 1 : 0,
                annotation_at: saved ? 1_760_000_950 : null,
                ...(saved ? { annotation_goal_saved_at: 1_760_000_950 } : {}),
                annotation_goal_source: '',
                annotation_goal_source_at: null,
                annotation_settled_through: null,
                reading_eligibility: { ok: true },
                ...(setup?.session ?? {}),
              },
            ],
          });
        }
        if (url.startsWith('/api/project-context')) {
          return json({
            semantic: { facts: FACTS },
            prompt_choices: [],
            sources: { work: { unavailable: [] } },
          });
        }
        if (url.startsWith('/api/session-record')) {
          return json({ state: 'ok', entries: [], next: null, reached_start: true });
        }
        if (url === '/api/annotate') saved = true;
        if (url === '/api/annotate') return json({ ok: true, persisted: true, outcome: 'saved' });
        if (url === '/api/reading') return json({ ok: true, produced: false });
        if (url === '/api/goal/find') return (setup?.find ?? (() => json(FOUND)))();
        if (url.startsWith('/api/annotations')) {
          return json({ annotations: [], intent_revision: 'r1' });
        }
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
  title: 'Intent/FindGoal',
  component: Harness,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Harness>;

export default meta;
type Story = StoryObj<typeof meta>;

const intentCard = (canvas: HTMLElement) => within(canvas).findByRole('region', { name: 'Intent' });
const finds = () =>
  (window.__findRequests ?? []).filter((request) => request.path === '/api/goal/find');
const note = (card: HTMLElement) =>
  (card.querySelector('[data-next-find-goal-note]')?.textContent ?? '').trim();

/* The button sits beside "Use your prompt", is labelled for what it does, and sends nothing until it is pressed. */
export const TheButtonBesideThePromptList: Story = {
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    const view = within(card);
    const button = await view.findByRole('button', { name: 'Find goal' });
    await expect(button).toBeVisible();
    await expect(button.title).toMatch(/Claude Code/);
    // Beside the prompt list, in the Goal field's heading row.
    const heading = button.closest('.next-cockpit-held-heading') as HTMLElement;
    await expect(within(heading).getByRole('button', { name: 'Use your prompt' })).toBeVisible();
    await expect(finds()).toEqual([]);
  },
};

/* A saved goal outranks anything found, so there is nothing to find: the button is not drawn. */
export const NoButtonOnceAGoalIsSaved: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Keep the parser small and pure',
        annotation_goal_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
        annotation_goal_saved_at: 1_760_000_500,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    await within(card).findByRole('textbox', { name: 'Goal' });
    await expect(within(card).queryByRole('button', { name: 'Find goal' })).toBeNull();
  },
};

/* So does a /goal the session set, which is already the working goal. */
export const NoButtonWhereASlashGoalWasDetected: Story = {
  args: {
    setup: {
      session: {
        session_goal: {
          text: 'The findings file exists and every check passes',
          at: 1_760_000_300,
        },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    await within(card).findByRole('textbox', { name: 'Goal' });
    await expect(card.querySelector('[data-next-goal-detected]')).toHaveTextContent(
      'Goal detected',
    );
    await expect(within(card).queryByRole('button', { name: 'Find goal' })).toBeNull();
  },
};

/* One press, one request. The goal fills the box with the same mark a /goal has, the line says where it came from
   and when, and each prompt it quotes is cited by its entry number. */
export const AFoundGoalWithItsCitations: Story = {
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    const view = within(card);
    await userEvent.click(await view.findByRole('button', { name: 'Find goal' }));
    await waitFor(() => expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(GOAL));
    await expect(finds()).toHaveLength(1);
    await expect(finds()[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      provider: 'claude',
      model: 'm',
      press: true,
      observer_model: 1,
    });
    await expect(card.querySelector('[data-next-goal-detected]')).toHaveTextContent(
      'Goal detected',
    );
    await expect(
      (card.querySelector('[data-next-cockpit-goal-source]')?.textContent ?? '').trim(),
    ).toMatch(/^Detected from your prompts · \d\d:\d\d · not saved$/);
    const cites = [
      ...card.querySelectorAll<HTMLElement>('[data-next-found-cites] [data-next-cite]'),
    ];
    await expect(cites.map((cite) => cite.textContent)).toEqual(['[1]', '[3]']);
    await expect(
      [...card.querySelectorAll('[data-next-found-quote]')].map((quote) => quote.textContent),
    ).toEqual([
      '#1 “add a retry to the upload client” “resume where it stopped”',
      '#3 “make sure the existing tests”',
    ]);
    await expect(cites[0]?.getAttribute('aria-label')).toBe(
      'Show #1 in Full activity for the detected goal',
    );
    // Found, so there is nothing left to find until the reader changes the words.
    await expect(view.queryByRole('button', { name: 'Find goal' })).toBeNull();
  },
};

/* A found goal is the working goal, as a /goal is: Analyze drift is not refused over it, Undo has nothing to
   undo, and the press stores the found words as typed words and then reads, adopting nothing. */
export const AFoundGoalIsAnalyzedWithoutASaveFirst: Story = {
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    const view = within(card);
    await userEvent.click(await view.findByRole('button', { name: 'Find goal' }));
    await waitFor(() => expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(GOAL));
    const analyze = await within(canvasElement).findByRole('button', { name: 'Analyze drift' });
    await waitFor(() => expect(analyze).not.toHaveAttribute('aria-disabled', 'true'));
    await expect(analyze).not.toBeDisabled();
    await expect(canvasElement).not.toHaveTextContent('Save your intent, or undo your edit');
    const undo = view.getByRole('button', { name: /Undo changes/ });
    await expect(undo).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(analyze);
    await waitFor(() =>
      expect((window.__findRequests ?? []).some((r) => r.path === '/api/reading')).toBe(true),
    );
    const sent = window.__findRequests ?? [];
    const paths = sent
      .map((r) => r.path)
      .filter((path) => path === '/api/annotate' || path === '/api/reading');
    await expect(paths).toEqual(['/api/annotate', '/api/reading']);
    await expect(sent.find((r) => r.path === '/api/annotate')?.body).toMatchObject({ goal: GOAL });
    await expect(sent.find((r) => r.path === '/api/reading')?.body).not.toHaveProperty('adopt');
  },
};

/* Pressing a citation shows the prompt in place and "See in context of the session" opens Full activity at
   that entry, as a cited entry on the Drift card does. */
export const ACitationOpensTheEntryInFullActivity: Story = {
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    await userEvent.click(await within(card).findByRole('button', { name: 'Find goal' }));
    const cite = await waitFor(() => {
      const node = card.querySelector<HTMLElement>('[data-next-found-cites] [data-next-cite="f2"]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await userEvent.click(cite);
    const shown = await waitFor(() => {
      const node = document.querySelector<HTMLElement>('[data-next-citation-card]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await userEvent.click(within(shown).getByText('See in context of the session'));
    await waitFor(() =>
      expect(document.activeElement).toBe(
        canvasElement.querySelector('[data-next-cockpit-work] [data-next-entry-id="f2"]'),
      ),
    );
    await expect(
      canvasElement
        .querySelector('[data-next-full-activity-trigger]')
        ?.getAttribute('aria-expanded'),
    ).toBe('true');
  },
};

/* Editing the found words replaces them: the mark, the line and the citations go, and Find goal comes back. */
export const EditingAFoundGoalReplacesIt: Story = {
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    const view = within(card);
    await userEvent.click(await view.findByRole('button', { name: 'Find goal' }));
    await waitFor(() => expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(GOAL));
    await userEvent.type(view.getByRole('textbox', { name: 'Goal' }), ' It is logged.');
    await expect(card.querySelector('[data-next-goal-detected]')).toBeNull();
    await expect(card.querySelector('[data-next-found-cites]')).toBeNull();
    await expect(
      (card.querySelector('[data-next-cockpit-goal-source]')?.textContent ?? '').trim(),
    ).toBe('Detected from your prompts, edited · not saved');
    await expect(await view.findByRole('button', { name: 'Find goal' })).toBeVisible();
  },
};

/* When the prompts do not make the goal clear the press says so beside the button, and the field stays as it was:
   the first prompt Compass drafted from, untouched. */
export const NothingFound: Story = {
  args: { setup: { find: () => json(NOTHING) } },
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    const view = within(card);
    const before = (view.getByRole('textbox', { name: 'Goal' }) as HTMLTextAreaElement).value;
    await userEvent.click(await view.findByRole('button', { name: 'Find goal' }));
    await waitFor(() => expect(note(card)).toBe(FIND_GOAL_NOTHING));
    await expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(before);
    await expect(before).toBe(FIRST);
    await expect(card.querySelector('[data-next-goal-detected]')).toBeNull();
    await expect(view.getByRole('button', { name: 'Find goal' })).toBeVisible();
    await expect(finds()).toHaveLength(1);
  },
};

/* Paused, it sends nothing and says why. */
export const PausedSendsNothingAndSaysSo: Story = {
  args: {
    setup: { policy: { consent: false, off: true, reason: 'model-calls-paused' } },
  },
  play: async ({ canvasElement }) => {
    const card = await intentCard(canvasElement);
    const view = within(card);
    await userEvent.click(await view.findByRole('button', { name: 'Find goal' }));
    await waitFor(() => expect(note(card)).toMatch(/paused/i));
    await expect(finds()).toEqual([]);
  },
};
