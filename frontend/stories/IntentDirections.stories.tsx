import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createShell } from '../src/shell/createShell';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

const AFTER = 'Then run the targeted tests, and push.';

function DirectionsExample({
  reason,
  count = 2,
  partial = false,
}: {
  readonly reason?: 'not_found' | 'out_of_reach' | 'changed';
  readonly count?: number;
  readonly partial?: boolean;
}) {
  const [shell] = useState(() => {
    const clock = createFakeClock();
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    let generation = 1000;
    const facts = Array.from({ length: count }, (_, index) => index + 1).map((n) => ({
      fact_id: `f${String(n)}`,
      type: 'user_message',
      at: 600 + n * 100,
      summary: `Build synthetic outcome ${String(n)}.`,
      source_session: { harness: 'claude', sid: 's1' },
      by: 'person:reader',
    }));
    return createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
        if (url.startsWith('/api/data'))
          return json({
            generated: generation++,
            annotate: true,
            annotate_cap: 240,
            annotate_goal_cap: 1000,
            sessions: [
              {
                harness: 'claude',
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic long session',
                state: 'idle',
                annotation_goal: 'Ship synthetic work',
                annotation_revision: 1,
                annotation_at: 500,
                annotation_goal_saved_at: 500,
                annotation_window_start: 500,
              },
            ],
          });
        if (url.startsWith('/api/project-context')) return json({ semantic: { facts } });
        if (url.startsWith('/api/session-record'))
          return json({ state: 'ok', entries: [], next: null, reached_start: true });
        if (url === '/api/direction') {
          const request = JSON.parse(String(init?.body)) as {
            fact_ids?: string[];
            fact_id?: string;
          };
          const single = (id: string) => {
            const n = Number(id.slice(1));
            const text = `Build synthetic outcome ${String(n)}. ${AFTER}`;
            return {
              ok: true,
              text,
              clipped: false,
              goal_choice: { fact_id: id, at: 600 + n * 100, text, cut: false },
            };
          };
          const answer = reason ? { ok: false, reason } : single(request.fact_id ?? 'f2');
          return json(
            request.fact_ids
              ? {
                  results: request.fact_ids.map((id) =>
                    partial && id === 'f2'
                      ? { ok: false, reason: 'out_of_reach' }
                      : reason
                        ? answer
                        : single(id),
                  ),
                }
              : answer,
          );
        }
        if (url === '/api/annotate')
          return json({
            ok: true,
            outcome: 'stored',
            persisted: true,
            revision: 2,
            saved_revision: 2,
            revision_count: 1,
          });
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
  return (
    <>
      <App shell={shell} />
      <button type="button" onClick={() => void shell.runtime.refresh()}>
        Simulate board poll
      </button>
    </>
  );
}

const meta = { title: 'Intent/Direction actions', component: DirectionsExample } satisfies Meta<
  typeof DirectionsExample
>;
export default meta;
type Story = StoryObj<typeof meta>;

async function failedPress(element: HTMLElement, action: string, message: string) {
  const button = element.querySelector(
    `[data-next-cockpit-action="${action}"]`,
  ) as HTMLButtonElement;
  await waitFor(() => expect(button).not.toBeNull());
  await userEvent.click(button);
  await waitFor(() =>
    expect(button.parentElement?.querySelector('[data-next-action-feedback]')).toHaveTextContent(
      message,
    ),
  );
  await expect(document.activeElement).toBe(button);
  await expect(document.querySelector('#next-cockpit-cue-status')).toHaveTextContent(message);
  await expect(document.querySelector('#next-cockpit-cue-status')).toHaveAttribute(
    'aria-live',
    'polite',
  );
  await expect(button).not.toHaveAttribute('aria-busy', 'true');
}

export const OutsideSearch: Story = {
  args: { reason: 'out_of_reach' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('button', { name: 'Leave it' });
    const prefix = 'That direction is beyond the part of the record Compass could search.';
    await failedPress(canvasElement, 'direction-goal', `${prefix} Your goal has not changed.`);
    await failedPress(canvasElement, 'direction-add', `${prefix} No outcome line was added.`);
    await failedPress(
      canvasElement,
      'direction-keep',
      `${prefix} Nothing was settled and no analysis was started.`,
    );
    // The row's own control is in Full activity, which starts collapsed.
    await userEvent.click(canvas.getByRole('button', { name: 'Full activity' }));
    const row = canvasElement.querySelector('[data-next-entry-id="f2"]') as HTMLElement;
    await failedPress(row, 'direction-add', `${prefix} No outcome line was added.`);
    await expect(canvas.getByRole('textbox', { name: 'Goal' })).toHaveValue('Ship synthetic work');
  },
};

/* The reader pressed while the agent was writing to its record, so the lookup saw the file move on every try.
   The sentence says so and asks for another press, where it used to say the direction was not verified. */
export const SessionWriting: Story = {
  args: { reason: 'changed' },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('button', { name: 'Leave it' });
    await failedPress(
      canvasElement,
      'direction-keep',
      'The session wrote to its record while Compass was reading it. Press again. Nothing was settled and no analysis was started.',
    );
  },
};

export const MissingRecord: Story = {
  args: { reason: 'not_found' },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('button', { name: 'Leave it' });
    await failedPress(
      canvasElement,
      'direction-keep',
      'That direction could not be verified as later than your intent in the current record. Nothing was settled and no analysis was started.',
    );
  },
};

export const TwentyTwoDirections: Story = {
  args: { count: 22 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Every direction is quoted whole before any press, so Leave it settles words already on screen.
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('.next-cockpit-direction-whole-item')).toHaveLength(22),
    );
    await waitFor(() =>
      expect(
        canvasElement.querySelectorAll('.next-cockpit-direction-whole-text')[21],
      ).toHaveTextContent('Build synthetic outcome 22. Then run the targeted tests, and push.'),
    );
    await expect(canvas.getByRole('button', { name: 'Leave it' })).not.toHaveAttribute(
      'aria-busy',
      'true',
    );
    await userEvent.click(canvas.getByRole('button', { name: 'Leave it' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-action-feedback]')).toHaveTextContent(
        'Kept your intent and settled all 22 directions. No analysis was started.',
      ),
    );
  },
};

/* A pending direction is quoted under its time before any press, beside the three choices and Analyze drift,
   and each choice acts on its first press. */
export const QuotedBeforeAnyPress: Story = {
  args: { count: 1 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText(/^Your \d\d:\d\d message adds:$/);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-cockpit-direction-whole]')).toHaveTextContent(
        `Build synthetic outcome 1. ${AFTER}`,
      ),
    );
    for (const name of ['Add as a line', 'Make it the goal', 'Leave it', 'Analyze drift'])
      await expect(canvas.getByRole('button', { name })).toBeVisible();
    // One press settles it: no second press to "read it first".
    await userEvent.click(canvas.getByRole('button', { name: 'Leave it' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-action-feedback]')).toHaveTextContent(
        'Kept your intent and settled the direction. No analysis was started.',
      ),
    );
  },
};

/* Analyze drift stays offered while a later direction waits, beside the choices and not instead of them. */
export const AnalyzeStaysAvailable: Story = {
  args: { count: 2 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText('2 later directions:');
    await expect(await canvas.findByRole('button', { name: 'Analyze drift' })).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Leave it' })).toBeVisible();
  },
};

/* Add as a line opens the rule, not the whole message, on the first press, with its hint, and the card's one
   Save intent saves it: the pending line draws no Save of its own. */
export const AddAsALineOneSave: Story = {
  args: { count: 2 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Add as a line' }));
    const line = await canvas.findByDisplayValue('Build synthetic outcome 2.');
    await expect(line.tagName).toBe('TEXTAREA');
    // A pending line opens the Expected outcome accordion, which eases open.
    await waitFor(() => expect(canvas.getByText('Write the rule, not the moment.')).toBeVisible());
    await expect(canvas.getAllByRole('button', { name: /^Save\b/ })).toHaveLength(1);
    await expect(canvas.getByRole('button', { name: 'Save intent' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
    await userEvent.click(canvas.getByRole('button', { name: 'Save intent' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-cockpit-direction-line]')).toBeNull(),
    );
  },
};

/* Make it the goal fills the goal with the rule on the first press, with the hint, and the same single Save. */
export const MakeItTheGoalOneSave: Story = {
  args: { count: 1 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Make it the goal' }));
    await waitFor(() =>
      expect(canvas.getByRole('textbox', { name: 'Goal' })).toHaveValue(
        'Build synthetic outcome 1.',
      ),
    );
    // A pending line opens the Expected outcome accordion, which eases open.
    await waitFor(() => expect(canvas.getByText('Write the rule, not the moment.')).toBeVisible());
    await expect(canvas.getAllByRole('button', { name: /^Save\b/ })).toHaveLength(1);
  },
};

export const PartialBatch: Story = {
  args: { partial: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('button', { name: 'Leave it' });
    await failedPress(
      canvasElement,
      'direction-keep',
      'That direction is beyond the part of the record Compass could search. Nothing was settled and no analysis was started.',
    );
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('.next-cockpit-direction-whole-item')).toHaveLength(1),
    );
    await expect(
      canvasElement.querySelector('.next-cockpit-direction-whole-text'),
    ).toHaveTextContent('Build synthetic outcome 1.');
    await userEvent.click(canvas.getByRole('button', { name: 'Leave it' }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-action-feedback]')).toHaveTextContent(
        'Nothing was settled and no analysis was started.',
      ),
    );
    await expect(canvasElement.querySelectorAll('.next-cockpit-direction-whole-item')).toHaveLength(
      1,
    );
  },
};

export const PhoneDirectionAndPendingLine: Story = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
  globals: { viewport: { value: 'mobile1', isRotated: false } },
  play: async ({ canvasElement }) => {
    const browserPage =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    const before = { width: window.innerWidth, height: window.innerHeight };
    if (browserPage) await browserPage.viewport(375, 667);
    try {
      if (browserPage) {
        await expect(window.innerWidth).toBe(375);
        await expect(window.innerHeight).toBe(667);
      }
      const canvas = within(canvasElement);
      await userEvent.click(await canvas.findByRole('button', { name: 'Add as a line' }));
      const line = await canvas.findByDisplayValue('Build synthetic outcome 2.');
      await expect(line.tagName).toBe('TEXTAREA');
      await expect(document.activeElement).toBe(line);
      await userEvent.clear(line);
      await userEvent.type(line, 'My reviewed synthetic outcome');
      await userEvent.click(canvas.getByRole('button', { name: 'Simulate board poll' }));
      await expect(line).toHaveValue('My reviewed synthetic outcome');
      await expect(line.getBoundingClientRect().width).toBeLessThanOrEqual(window.innerWidth);
      await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      await expect(canvas.getByRole('button', { name: 'Save intent' })).toBeVisible();
      await expect(canvas.getByRole('button', { name: 'Remove' })).toBeVisible();
    } finally {
      if (browserPage) await browserPage.viewport(before.width, before.height);
    }
  },
};
