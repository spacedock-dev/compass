import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { ENDED_CAVEAT, INTENT_LEDE, INTENT_MEASURED } from '../src/intent/sentences';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const SESSION_ROUTE = '#n=session:alpha%2Fapp:claude:s1';

interface CardSetup {
  readonly session?: Record<string, unknown>;
  readonly facts?: readonly Record<string, unknown>[];
  readonly prompts?: readonly Record<string, unknown>[];
  readonly onAnnotate?: (body: Record<string, unknown>) => Response | Promise<Response>;
}

function buildPayload(
  sessionOverrides: Record<string, unknown> = {},
  generated = 1_760_001_000,
): Record<string, unknown> {
  return {
    generated,
    annotate: true,
    annotate_cap: 240,
    intent_revision: 'r1',
    annotate_discard: {
      why: 'Deletes the saved goal, outcome lines and readings for this session.',
      armed: 'Press Confirm discard to delete every saved revision for this session.',
      stored: 'Discarded.',
      refused: 'Could not discard.',
      unwritable: 'Could not write discard.',
      record: 'Discarded.',
    },
    projects: [{ project: 'alpha/app', project_key: '/repo/alpha', sessions: ['claude:s1'] }],
    sessions: [
      {
        harness: 'claude',
        sid: 's1',
        project: 'alpha/app',
        project_key: '/repo/alpha',
        title: 'Parser cleanup',
        state: 'working',
        started_at: 1_760_000_000,
        last_event_at: 1_760_000_900,
        first_prompt: 'Keep the parser small and pure',
        first_prompt_at: 1_760_000_100,
        latest_prompt: 'Keep the parser small and pure',
        latest_prompt_at: 1_760_000_100,
        annotation_goal: '',
        annotation_goal_why: 'No goal typed for this session.',
        annotation_lines_why: 'No expected outcome typed.',
        annotation_revision: 0,
        annotation_revision_count: 0,
        annotation_at: null,
        annotation_goal_source: '',
        annotation_goal_source_at: null,
        annotation_settled_through: null,
        reading_eligibility: { ok: true },
        ...sessionOverrides,
      },
    ],
  };
}

function IntentCardHarness({ setup }: { readonly setup?: CardSetup }) {
  const [shell] = useState(() => {
    const clock = createFakeClock();
    const history = fakeRouterEnvironment(SESSION_ROUTE);
    let generation = 1_760_001_000;
    let currentSession: Record<string, unknown> = { ...(setup?.session ?? {}) };
    const prompts = setup?.prompts ?? [
      {
        fact_id: 'p1',
        text: 'Keep the parser small and pure',
        at: 1_760_000_100,
        cut: false,
      },
      {
        fact_id: 'p2',
        text: 'Add streaming tokenizer benchmarks before touching the AST',
        at: 1_760_000_400,
        cut: true,
      },
    ];
    const facts = setup?.facts ?? [
      {
        fact_id: 'p1',
        type: 'user_message',
        by: 'person:me',
        summary: 'Keep the parser small and pure',
        at: 1_760_000_100,
        source_session: { harness: 'claude', sid: 's1' },
      },
    ];
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });

    const instance = createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url.startsWith('/api/data')) {
          return json(buildPayload(currentSession, generation++));
        }
        if (url.startsWith('/api/project-context')) {
          return json({
            semantic: { facts },
            prompt_choices: prompts,
            sources: { work: { unavailable: [] } },
          });
        }
        if (url.startsWith('/api/session-record')) {
          return json({ state: 'ok', entries: [], next: null, reached_start: true });
        }
        if (url === '/api/annotate') {
          const body =
            typeof init?.body === 'string' && init.body
              ? (JSON.parse(init.body) as Record<string, unknown>)
              : {};
          if (setup?.onAnnotate) {
            return setup.onAnnotate(body);
          }
          const nextRev = Number(currentSession['annotation_revision'] ?? 0) + 1;
          const adopt = typeof body['adopt'] === 'string' ? body['adopt'] : '';
          const goal = adopt
            ? String(body['expected_prompt'] ?? '')
            : typeof body['goal'] === 'string'
              ? body['goal']
              : String(currentSession['annotation_goal'] ?? '');
          currentSession = {
            ...currentSession,
            annotation_goal: goal,
            annotation_goal_why: goal ? '' : 'No goal typed for this session.',
            annotation_revision: nextRev,
            annotation_revision_count: nextRev,
            annotation_at: 1_760_000_950,
            annotation_goal_saved_at: 1_760_000_950,
            annotation_goal_source: adopt || (typeof body['goal'] === 'string' ? 'typed' : ''),
            annotation_goal_source_at: adopt
              ? Number(body['expected_prompt_at'] ?? 1_760_000_100)
              : null,
          };
          return json({
            ok: true,
            outcome: 'stored',
            persisted: true,
            revision: nextRev,
            saved_revision: nextRev,
            revision_count: nextRev,
          });
        }
        if (url.startsWith('/api/annotations')) {
          return json({ annotations: [], intent_revision: 'r1' });
        }
        return json({});
      },
    });

    (
      window as unknown as {
        __updateIntentSession?: (patch: Record<string, unknown>) => Promise<void>;
      }
    ).__updateIntentSession = async (patch: Record<string, unknown>) => {
      currentSession = { ...currentSession, ...patch };
      await instance.runtime.refresh();
    };

    return instance;
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
  title: 'Intent/IntentCard',
  component: IntentCardHarness,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof IntentCardHarness>;

export default meta;
type Story = StoryObj<typeof meta>;

export const TypedSourceAndSavedStatus: Story = {
  args: {
    setup: {
      session: {
        first_prompt: '',
        first_prompt_at: null,
        latest_prompt: '',
        latest_prompt_at: null,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await expect(view.getByText(INTENT_LEDE)).toBeVisible();
    await expect(view.getByText(/Expected outcome/)).toHaveTextContent(
      'Expected outcome · up to 6 lines',
    );
    await expect(card.querySelector('[data-next-cockpit-held-line-number="0"]')).toHaveTextContent(
      '1',
    );
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await expect(goal).toHaveAttribute('placeholder', 'What should this session achieve?');
    await userEvent.type(goal, 'Keep the parser small and pure');
    await expect(view.getByText('Typed · not saved')).toBeVisible();
    await expect(view.getByText('30 / 240')).toBeVisible();
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saved');
    });
    await expect(view.getByText(/^Typed · saved \d\d:\d\d$/)).toBeVisible();
  },
};

export const FromPromptSource: Story = {
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await expect(goal).toHaveValue('Keep the parser small and pure');
    await expect(
      view.getByText(
        'From your prompt · first · not saved. Analyze reads at most the first 1,000 characters of any prompt.',
      ),
    ).toBeVisible();
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
  },
};

export const AdoptedThenEditedSource: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Keep the parser small and pure',
        annotation_goal_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
        annotation_goal_saved_at: 1_760_000_500,
        annotation_goal_source: 'first-prompt',
        annotation_goal_source_at: 1_760_000_100,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saved');
    await expect(view.getByText('From your prompt · first · saved')).toBeVisible();
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ', and fast');
    await expect(view.getByText('From your prompt, edited · not saved')).toBeVisible();
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
  },
};

export const SavingStatus: Story = {
  render: () => {
    let releaseSave: (() => void) | null = null;
    (window as unknown as { __releaseIntentSave?: () => void }).__releaseIntentSave = () =>
      releaseSave?.();
    return (
      <IntentCardHarness
        setup={{
          onAnnotate: () =>
            new Promise<Response>((resolve) => {
              releaseSave = () => {
                void (
                  window as unknown as {
                    __updateIntentSession?: (patch: Record<string, unknown>) => Promise<void>;
                  }
                ).__updateIntentSession?.({
                  annotation_goal: 'Keep the parser small and pure',
                  annotation_goal_why: '',
                  annotation_revision: 1,
                  annotation_revision_count: 1,
                  annotation_at: 1_760_000_950,
                  annotation_goal_saved_at: 1_760_000_950,
                  annotation_goal_source: 'first-prompt',
                  annotation_goal_source_at: 1_760_000_100,
                });
                resolve(
                  new Response(
                    JSON.stringify({
                      ok: true,
                      outcome: 'stored',
                      persisted: true,
                      revision: 1,
                      saved_revision: 1,
                      revision_count: 1,
                    }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } },
                  ),
                );
              };
            }),
        }}
      />
    );
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saving…');
    });
    (window as unknown as { __releaseIntentSave?: () => void }).__releaseIntentSave?.();
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saved');
    });
  },
};

export const NotConfirmedStatus: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Saved goal',
        annotation_goal_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
      },
      onAnnotate: () => new Response('<html>', { status: 200 }),
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ' edited');
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
        'Not confirmed',
      );
    });
    await expect(
      view.getByText(
        /Compass did not answer, so this page cannot tell whether your intent was saved/,
      ),
    ).toBeVisible();
  },
};

export const RefusedStatus: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Saved goal',
        annotation_goal_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
      },
      onAnnotate: () =>
        new Response(JSON.stringify({ ok: true, outcome: 'refused', persisted: false }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ' edited');
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Not saved');
    });
    await expect(
      view.getByText(
        'Not saved. The server refused the write, and your words are still in the box.',
      ),
    ).toBeVisible();
  },
};

export const ConcurrentRevisionKeepsUnsavedChanges: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Initial goal',
        annotation_goal_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saved');
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ' — local draft');
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
    await (
      window as unknown as {
        __updateIntentSession?: (patch: Record<string, unknown>) => Promise<void>;
      }
    ).__updateIntentSession?.({
      annotation_goal: 'Saved from another tab',
      annotation_revision: 2,
      annotation_revision_count: 2,
      annotation_at: 1_760_000_800,
    });
    await expect(goal).toHaveValue('Initial goal — local draft');
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
  },
};

export const PromptMenuPick: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Saved goal',
        annotation_goal_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    const trigger = view.getByRole('combobox', { name: 'Use your prompt' });
    await userEvent.click(trigger);
    const doc = within(canvasElement.ownerDocument.body);
    await waitFor(async () => {
      await expect(doc.getByText('Your prompts in this session')).toBeVisible();
    });
    const option = await doc.findByRole('option', {
      name: /Latest prompt · \d\d:\d\d · excerpt Add streaming tokenizer benchmarks/,
    });
    await userEvent.click(option);
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await expect(goal).toHaveValue('Add streaming tokenizer benchmarks before touching the AST');
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
    await expect(
      view.getByText(
        /From your prompt · \d\d:\d\d · not saved\. Analyze reads at most the first 1,000 characters of any prompt\./,
      ),
    ).toBeVisible();
  },
};

export const MovedControlsInQuietRow: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Keep the parser small and pure',
        annotation_goal_why: '',
        annotation_line_1: 'All parser unit tests pass',
        annotation_lines_why: '',
        annotation_revision: 2,
        annotation_revision_count: 2,
        annotation_at: 1_760_000_500,
        annotation_goal_saved_at: 1_760_000_500,
        annotation_window_start: 1_760_000_100,
        annotation_settled_through: 1_760_000_600,
        annotation_settled_at: 1_760_000_700,
        annotation_settled_revision: 2,
      },
      facts: [
        {
          fact_id: 'f1',
          type: 'user_message',
          by: 'person:me',
          summary: 'Keep it strict',
          at: 1_760_000_600,
          source_session: { harness: 'claude', sid: 's1' },
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const kept = card.querySelector('[data-next-intent-kept]') as HTMLElement;
    await expect(kept).not.toBeNull();
    const quiet = within(kept);
    await expect(quiet.getByText(INTENT_MEASURED)).toBeVisible();
    await expect(quiet.getByRole('button', { name: /^Saved · reads from/ })).toBeVisible();
    await expect(quiet.getAllByRole('button', { name: 'Discard everything' })[0]).toBeVisible();
    await expect(
      await quiet.findByRole('button', { name: /^Later directions: settled/ }),
    ).toBeVisible();
    // Every count reads "n / cap", the outcome lines' as the goal's.
    await expect(within(card).getByText('26 / 240')).toBeVisible();
    // The stamp opens its definition from the quiet row.
    await userEvent.click(quiet.getByRole('button', { name: /^Saved · reads from/ }));
    await waitFor(() => expect(quiet.getByText('Each save is a revision.')).toBeVisible());
    // Discard everything arms from the quiet row, and Escape disarms it without a write.
    await userEvent.click(
      quiet.getAllByRole('button', { name: 'Discard everything' })[0] as HTMLElement,
    );
    await waitFor(() =>
      expect(quiet.getAllByRole('button', { name: 'Discard everything' })).toHaveLength(2),
    );
    await userEvent.click(
      quiet.getAllByRole('button', { name: 'Discard everything' })[1] as HTMLElement,
    );
    const confirm = await quiet.findByRole('button', { name: 'Confirm discard' });
    await expect(confirm).toBeVisible();
    confirm.focus();
    await userEvent.keyboard('{Escape}');
    await waitFor(() =>
      expect(quiet.queryByRole('button', { name: 'Confirm discard' })).toBeNull(),
    );
    await expect(within(card).getByRole('textbox', { name: 'Goal' })).toHaveValue(
      'Keep the parser small and pure',
    );
    const clear = quiet.getByRole('button', { name: 'Clear' });
    await userEvent.click(clear);
    await expect(within(card).getByRole('textbox', { name: 'Goal' })).toHaveValue('');
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      'Unsaved changes',
    );
  },
};

export const EndedSessionCaveatBeforeAndAfterSave: Story = {
  args: {
    setup: {
      session: {
        state: 'ended',
        ended_at: 1_760_000_800,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await expect(card.querySelector('[data-next-ended-goal]')).toHaveTextContent(ENDED_CAVEAT);
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ' after end');
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(
        card.querySelector('.next-cockpit-held-footer .next-cockpit-held-cue'),
      ).toHaveTextContent(`Saved as a new revision. ${ENDED_CAVEAT}`);
    });
  },
};
