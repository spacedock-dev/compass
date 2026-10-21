import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { App } from '../src/App';
import { ENDED_CAVEAT, INTENT_LEDE, INTENT_MEASURED } from '../src/intent/sentences';
import { clock } from '../src/observed';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const SESSION_ROUTE = '#n=session:alpha%2Fapp:claude:s1';
/* The reader's latest message in the stories that move a reading's start, after the start they open at. */
const LATEST_MESSAGE = 1_760_000_700;
const FIRST_START = 1_760_000_200;

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
    /* The server's own sentences, as `annotations.DISCARD_SENTENCES` words them: this page draws them and
       composes none, so a story that quotes them holds the page to what the server said it would remove and keep. */
    annotate_discard: {
      why: 'Discarding everything deletes every revision of what you asked of this session, any reading of it, and this session’s summary, and nothing raised against those words quotes them any more. It keeps the record that a check ran, which bounds how often one may run. Session history, where it is recording, keeps its own fourteen-day copy, and --forget deletes that store. The clear beside the goal is the weaker act: the save after it keeps every earlier revision.',
      armed:
        'Press it again to discard. Every revision of what you asked of this session will go, along with any reading of it and this session’s summary, including one being written, and nothing raised against those words will quote them any more; the record that a check ran stays. Nothing has been deleted yet, and this offer lapses in 30 seconds.',
      stored:
        'Discarded. Every revision of what you asked of this session is gone, along with any reading of it and its summary, and nothing raised against those words quotes them any more. The record that a check ran stays, because it is what bounds how often one may run.',
      refused: 'Could not discard.',
      unwritable: 'Could not write discard.',
      record:
        'What you asked of this session was discarded, along with any reading of it. None of it is kept here: this record says only that the act happened and when.',
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
          const hold = (window as unknown as { __holdIntentData?: Promise<void> }).__holdIntentData;
          if (hold) await hold;
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
          /* The server's rule (docs/design-reading-a-session.md, "Amended 2026-10-21 (owner): editing the goal
             keeps the reading's start"): a save over a window keeps it, and only Read from now reopens it, at
             the reader's latest message. A session that published no window keeps publishing none. */
          const opened = Number(currentSession['annotation_window_start'] ?? 0);
          const window =
            opened > 0
              ? {
                  annotation_window_start: body['read_from_now'] === true ? LATEST_MESSAGE : opened,
                }
              : {};
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
            ...window,
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
    (window as unknown as { __advanceIntentClock?: (ms: number) => void }).__advanceIntentClock = (
      ms,
    ) => clock.advance(ms);

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
    await expect(view.getByText('From your prompt · first · not saved.')).toBeVisible();
    /* A goal drafted from the prompt is Compass's suggestion, not the reader's edit: muted, and saying what
       it is (usability review, 2026-10-20). */
    const status = card.querySelector('[data-next-intent-status]') as HTMLElement;
    await expect(status).toHaveTextContent(/^Draft$/);
    await expect(status).not.toHaveTextContent('Unsaved changes');
    await expect(status.className).toContain('text-muted-foreground');
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

const READING_FROM_ORIGINAL = {
  annotation_goal: 'Keep the parser small and pure',
  annotation_goal_why: '',
  annotation_revision: 1,
  annotation_revision_count: 1,
  annotation_at: 1_760_000_500,
  annotation_window_start: FIRST_START,
};

/* The owner's ruling of 2026-10-21: widening the goal does not move where the reading starts, so the work
   already done toward it stays read. The start is the line "Saved · reads from" beside the card. */
export const GoalEditKeepsTheReadingStart: Story = {
  args: { setup: { session: READING_FROM_ORIGINAL } },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await expect(
      view.getByRole('button', { name: new RegExp(`Saved · reads from ${clock(FIRST_START)}`) }),
    ).toBeVisible();
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.type(goal, ' and record the ruling');
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(
        card.querySelector('.next-cockpit-held-footer .next-cockpit-held-cue'),
      ).toHaveTextContent('Saved as a new revision.');
    });
    await waitFor(async () => {
      await expect(
        view.getByRole('button', { name: new RegExp(`Saved · reads from ${clock(FIRST_START)}`) }),
      ).toBeVisible();
    });
    await expect(view.queryByText(new RegExp(clock(LATEST_MESSAGE)))).toBeNull();
  },
};

export const UsingAPromptAsTheGoalKeepsTheReadingStart: Story = {
  args: { setup: { session: READING_FROM_ORIGINAL } },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    await userEvent.click(view.getByRole('combobox', { name: 'Use your prompt' }));
    const doc = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await doc.findByRole('option', { name: /Latest prompt · \d\d:\d\d · excerpt Add streaming/ }),
    );
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(
        'Add streaming tokenizer benchmarks before touching the AST',
      );
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saved');
    });
    await expect(
      view.getByRole('button', { name: new RegExp(`Saved · reads from ${clock(FIRST_START)}`) }),
    ).toBeVisible();
  },
};

export const ReadFromNowMovesTheStartAndSaysSo: Story = {
  args: { setup: { session: READING_FROM_ORIGINAL } },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    const now = view.getByRole('button', { name: 'Read from now' });
    await expect(now).toHaveAttribute('aria-disabled', 'true');
    await userEvent.type(view.getByRole('textbox', { name: 'Goal' }), ' and record the ruling');
    await expect(now).not.toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(now);
    await waitFor(async () => {
      await expect(
        card.querySelector('.next-cockpit-held-footer .next-cockpit-held-cue'),
      ).toHaveTextContent(
        `Saved. Compass now reads from ${clock(LATEST_MESSAGE)}. Work before that is not read.`,
      );
    });
    await expect(
      view.getByRole('button', { name: new RegExp(`Saved · reads from ${clock(LATEST_MESSAGE)}`) }),
    ).toBeVisible();
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
    await expect(view.getByText(/^From your prompt · \d\d:\d\d · not saved\./)).toBeVisible();
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
    // The row keeps only the reading start and the menu; everything else is one press away.
    await expect(within(kept).getByRole('button', { name: /^Saved · reads from/ })).toBeVisible();
    await expect(within(kept).queryByRole('button', { name: 'Clear' })).toBeNull();
    await userEvent.click(within(kept).getByRole('button', { name: 'More about these words' }));
    const quiet = within(canvasElement);
    await waitFor(async () => expect(await quiet.findByText(INTENT_MEASURED)).toBeVisible());
    await expect(quiet.getAllByRole('button', { name: 'Discard everything' })[0]).toBeVisible();
    await expect(
      await quiet.findByRole('button', { name: /^Later directions: settled/ }),
    ).toBeVisible();
    // Every count reads "n / cap", the outcome lines' as the goal's.
    await expect(within(card).getByText('26 / 240')).toBeVisible();
    // The stamp opens its definition from the quiet row.
    await userEvent.click(within(kept).getByRole('button', { name: /^Saved · reads from/ }));
    await waitFor(() => expect(quiet.getByText('Each save is a revision.')).toBeVisible());
    // Pressing the stamp moves focus out of the menu, which closes it; the menu opens again for the rest.
    const more = within(kept).getByRole('button', { name: 'More about these words' });
    if (more.getAttribute('aria-expanded') !== 'true') await userEvent.click(more);
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
    // Escape disarmed the discard and closed the menu with it; Clear is one more open away.
    const again = within(kept).getByRole('button', { name: 'More about these words' });
    await waitFor(() => expect(again).toHaveAttribute('aria-expanded', 'false'));
    await userEvent.click(again);
    await userEvent.click(await quiet.findByRole('button', { name: 'Clear' }));
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

/* The card held the drafted prompt while the board refresh that follows a save was in flight: the typed words
   were dropped when the reply landed and came back when the row did. */
export const TypedWordsStayThroughSlowSave: Story = {
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const view = within(card);
    const goal = view.getByRole('textbox', { name: 'Goal' });
    await userEvent.clear(goal);
    await userEvent.type(goal, 'Keep the parser pure and small');
    await userEvent.type(
      view.getByRole('textbox', { name: 'Expected outcome line 1' }),
      'Tests pass',
    );
    let release: () => void = () => undefined;
    (window as unknown as { __holdIntentData?: Promise<void> }).__holdIntentData =
      new Promise<void>((resolve) => {
        release = resolve;
      });
    await userEvent.click(view.getByRole('button', { name: 'Save intent' }));
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saving…');
    });
    // Let the annotate reply land while the refresh is still held.
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saving…');
    await expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(
      'Keep the parser pure and small',
    );
    await expect(view.getByRole('textbox', { name: 'Expected outcome line 1' })).toHaveValue(
      'Tests pass',
    );
    release();
    await waitFor(async () => {
      await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent('Saved');
    });
    await expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(
      'Keep the parser pure and small',
    );
    delete (window as unknown as { __holdIntentData?: Promise<void> }).__holdIntentData;
  },
};

/* The five states of the card, each held to the design: a three-row goal, Add a line, Save intent and Undo
   changes together on the left and drawn from the first view, one word of status, and the card's meta row
   reduced to the reading start beside one quiet menu. */
async function controlsTogether(card: HTMLElement) {
  const view = within(card);
  const add = view.getByRole('button', { name: '+ Add a line' });
  const save = view.getByRole('button', { name: 'Save intent' });
  const undo = view.getByRole('button', { name: 'Undo changes' });
  await expect(add).toBeVisible();
  await expect(save).toBeVisible();
  await expect(undo).toBeVisible();
  const [a, s, u] = [add, save, undo].map((node) => node.getBoundingClientRect());
  // One row, in the design's order, starting at the card's left edge rather than split to its two ends.
  await expect(Math.abs((a?.top ?? 0) - (s?.top ?? 1))).toBeLessThan(4);
  await expect((a?.right ?? 0) <= (s?.left ?? 0)).toBe(true);
  await expect((s?.right ?? 0) <= (u?.left ?? 0)).toBe(true);
  await expect((u?.right ?? 0) - (a?.left ?? 0)).toBeLessThan(
    card.getBoundingClientRect().width / 2,
  );
  const goal = view.getByRole('textbox', { name: 'Goal' });
  await expect(goal.getBoundingClientRect().height).toBeGreaterThan(60);
  await expect(view.getByRole('button', { name: 'Remove line 1' })).toBeVisible();
  await expect(view.queryByRole('button', { name: 'Replace with your prompt' })).toBeNull();
  await expect(card.querySelector('[data-next-intent-status]')?.textContent ?? '').not.toMatch(
    /how intent/i,
  );
  await expect(view.queryByRole('button', { name: 'How Intent and drift works' })).toBeNull();
  await expect(view.queryByRole('button', { name: 'Clear' })).toBeNull();
  await expect(view.queryByText(INTENT_MEASURED)).toBeNull();
  return { view, save, undo };
}

const inert = (node: HTMLElement) => node.getAttribute('aria-disabled') === 'true';

export const StateEmpty: Story = {
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
    const card = await within(canvasElement).findByRole('region', { name: 'Intent' });
    const { save, undo } = await controlsTogether(card);
    await expect(card.querySelector('[data-next-intent-status]')).toBeNull();
    await expect(inert(save)).toBe(true);
    await expect(inert(undo)).toBe(true);
    await expect(card.querySelector('[data-next-intent-kept]')?.textContent ?? '').toBe('More');
  },
};

export const StateDrafted: Story = {
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Intent' });
    const { view, save } = await controlsTogether(card);
    await expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(
      'Keep the parser small and pure',
    );
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(/^Draft$/);
    await expect(inert(save)).toBe(false);
    // The prompt-length sentence is under "What is sent", not in the goal's hint.
    await expect(view.queryByText(/1,000 characters/)).toBeNull();
  },
};

export const StateEdited: Story = {
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Intent' });
    const view = within(card);
    await userEvent.type(view.getByRole('textbox', { name: 'Goal' }), ' and fast');
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(
      /^Unsaved changes$/,
    );
    const { undo } = await controlsTogether(card);
    await expect(inert(undo)).toBe(false);
    await userEvent.click(undo);
    await expect(view.getByRole('textbox', { name: 'Goal' })).toHaveValue(
      'Keep the parser small and pure',
    );
  },
};

export const StateSaved: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Keep the parser small and pure',
        annotation_goal_why: '',
        annotation_line_1: 'All parser unit tests pass',
        annotation_lines_why: '',
        annotation_revision: 1,
        annotation_revision_count: 1,
        annotation_at: 1_760_000_500,
        annotation_goal_saved_at: 1_760_000_500,
        annotation_window_start: 1_760_000_100,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Intent' });
    const view = within(card);
    await expect(card.querySelector('[data-next-intent-status]')).toHaveTextContent(/^Saved$/);
    await expect(view.getByRole('button', { name: /^Saved · reads from/ })).toBeVisible();
    // The row holds the reading start and the menu, nothing else.
    const kept = card.querySelector('[data-next-intent-kept]') as HTMLElement;
    await expect(
      within(kept)
        .getAllByRole('button')
        .map((node) => node.textContent),
    ).toEqual([expect.stringMatching(/^Saved · reads from/), 'More']);
    await controlsTogether(card);
  },
};

/* Discard everything says what it removes and what it keeps before the second press, and once, after it. The form
   is left empty, not refilled from the session's first prompt, which stays one press away under Use your prompt. */
export const DiscardEverythingSaysWhatGoesAndWhatStays: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: 'Keep the parser small and pure',
        annotation_goal_why: '',
        annotation_revision: 2,
        annotation_revision_count: 2,
        annotation_at: 1_760_000_500,
        annotation_goal_saved_at: 1_760_000_500,
      },
      onAnnotate: async (body) => {
        if (body['clear'] === true) {
          await (
            window as unknown as {
              __updateIntentSession: (patch: Record<string, unknown>) => Promise<void>;
            }
          ).__updateIntentSession({
            annotation_goal: '',
            annotation_goal_why: 'Discarded with everything else you asked of this session.',
            annotation_revision: 0,
            annotation_revision_count: 0,
            annotation_discarded_at: 1_760_001_000,
          });
        }
        return new Response(
          JSON.stringify({
            ok: true,
            outcome: 'stored',
            persisted: true,
            withdrew: true,
            summary: 'deleted',
            discarded: 1_760_001_000,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement);
    const card = await page.findByRole('region', { name: 'Intent' });
    const kept = card.querySelector('[data-next-intent-kept]') as HTMLElement;
    await userEvent.click(within(kept).getByRole('button', { name: 'More about these words' }));
    const quiet = within(canvasElement);
    await userEvent.click(
      (await quiet.findAllByRole('button', { name: 'Discard everything' }))[0] as HTMLElement,
    );
    // Before the press: what goes, and what stays.
    const why = await quiet.findByText(/^Discarding everything deletes every revision/);
    for (const named of [
      'any reading of it',
      'this session’s summary',
      'It keeps the record that a check ran',
      'Session history',
      '--forget',
    ]) {
      await expect(why).toHaveTextContent(named);
    }
    await userEvent.click(
      (await quiet.findAllByRole('button', { name: 'Discard everything' }))[1] as HTMLElement,
    );
    const confirm = await quiet.findByRole('button', { name: 'Confirm discard' });
    // The confirmation says the same of the summary, including one being written, and says when it lapses.
    const armed = canvasElement.querySelector('#next-cockpit-discard-armed') as HTMLElement;
    await expect(armed).toHaveTextContent('this session’s summary, including one being written');
    await expect(armed).toHaveTextContent('this offer lapses in 30 seconds');
    await expect(armed).not.toHaveTextContent('on its own');
    (window as unknown as { __advanceIntentClock: (ms: number) => void }).__advanceIntentClock(
      1_300,
    );
    await userEvent.click(confirm);
    // After: one sentence naming what went and what stays, and a goal left empty.
    const said = await waitFor(() => {
      const node = card.querySelector<HTMLElement>(
        '.next-cockpit-held-discard .next-cockpit-held-cue',
      );
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await expect(said).toHaveTextContent('along with any reading of it and its summary');
    await expect(said).toHaveTextContent('The record that a check ran stays');
    await expect(within(card).getByRole('textbox', { name: 'Goal' })).toHaveValue('');
    await expect(canvasElement.textContent).not.toContain('Draft from your first prompt');
    await expect(canvasElement.textContent).not.toMatch(/\b0 drift checks? requested/);
    // The record of the act is not said beside its own result as well.
    await expect(canvasElement.textContent).not.toContain(
      'None of it is kept here: this record says only',
    );
  },
};

export const StateDiscarded: Story = {
  args: {
    setup: {
      session: {
        annotation_goal: '',
        annotation_goal_why: 'No goal typed for this session.',
        annotation_revision: 0,
        annotation_revision_count: 0,
        annotation_discarded_at: 1_760_000_900,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const card = await within(canvasElement).findByRole('region', { name: 'Intent' });
    await expect(card).toHaveTextContent(/discarded/);
    await expect(card.querySelector('[data-next-intent-status]')?.textContent ?? '').not.toBe(
      'Saved',
    );
    await controlsTogether(card);
  },
};
