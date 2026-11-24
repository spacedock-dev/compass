import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { auditCalm } from './calm.audit';

/* A Sessions row as the redesign canvas draws it (owner request, 2026-11-24): the status tile, the title, one
   descriptor line naming the harness, project and start (and the end, once there is one), the Now line under
   it, and the goal to the right. No column header strip, and no Project, Next or Blocked column: a session
   blocked on you wears the Waiting on you tile and keeps its question under the Now line. Every name and
   sentence here is invented. */

const meta = { title: 'Sessions/Canvas row' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const G = 1900000000;
const QUESTION = 'Run the billing migration against the staging copy first?';

function Board() {
  const [shell] = useState(() => {
    const history = fakeRouterEnvironment('#n=sessions');
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: (url) =>
        Promise.resolve(
          url.startsWith('/api/data')
            ? json({
                generated: G,
                annotate: true,
                window_hours: 24,
                harnesses: [
                  {
                    key: 'claude',
                    label: 'Claude',
                    reports_rate: true,
                    reports_needs_input: true,
                    discovered: true,
                  },
                ],
                ask: true,
                asks: [
                  {
                    id: 'q1',
                    session_id: 'acme-billing',
                    harness: 'claude',
                    question: QUESTION,
                    options: ['Yes, staging first', 'Not yet'],
                    age_sec: 120,
                  },
                ],
                sessions: [
                  {
                    harness: 'claude',
                    sid: 'acme-docs',
                    project: 'acme/dashboard',
                    project_key: '/acme/dashboard',
                    title: 'Write the dashboard docs',
                    state: 'working',
                    active: true,
                    state_detail: 'Running 3 helpers · writing the docs pull request',
                    started_at: G - 5400,
                    last_activity: G - 10,
                    annotation_goal: 'Publish the dashboard guide with screenshots',
                    annotation_revision: 1,
                  },
                  {
                    harness: 'claude',
                    sid: 'acme-billing',
                    project: 'acme/api',
                    project_key: '/acme/api',
                    title: 'Migrate the billing tables',
                    state: 'needs_input',
                    state_detail: 'Waiting for you to approve a command',
                    blocked_since: G - 120,
                    started_at: G - 1800,
                    last_activity: G - 120,
                  },
                  {
                    harness: 'claude',
                    sid: 'acme-cleanup',
                    project: 'acme/api',
                    project_key: '/acme/api',
                    title: 'Remove the old feature flags',
                    state: 'idle',
                    started_at: G - 7200,
                    ended_at: G - 1500,
                    last_activity: G - 1500,
                    dirty: false,
                  },
                ],
              })
            : json({}),
        ),
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

async function atWidth(width: number, check: () => Promise<void>) {
  const browserPage =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (browserPage) await browserPage.viewport(width, 900);
  try {
    if (browserPage) await expect(window.innerWidth).toBe(width);
    await check();
  } finally {
    if (browserPage) await browserPage.viewport(before.width, before.height);
  }
}

const rowOf = (root: HTMLElement, sid: string) => {
  const row = root.querySelector<HTMLElement>(
    `article.next-operation-row[data-next-session="${sid}"]`,
  );
  if (!row) throw new Error(`Missing row ${sid}`);
  return row;
};
const part = (row: HTMLElement, selector: string) => {
  const found = row.querySelector<HTMLElement>(selector);
  if (!found) throw new Error(`Missing ${selector}`);
  return found;
};
const below = async (upper: HTMLElement, lower: HTMLElement) =>
  expect(lower.getBoundingClientRect().top).toBeGreaterThanOrEqual(
    upper.getBoundingClientRect().bottom - 1,
  );

export const DescriptorAndNow: Story = {
  render: () => <Board />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(3),
    );
    const docs = rowOf(canvasElement, 'acme-docs');
    const billing = rowOf(canvasElement, 'acme-billing');
    const cleanup = rowOf(canvasElement, 'acme-cleanup');

    await expect(part(docs, '[data-next-row-descriptor]').textContent).toBe(
      'Claude · acme/dashboard · started 1 hour 30 minutes ago',
    );
    await expect(part(billing, '[data-next-row-descriptor]').textContent).toBe(
      'Claude · acme/api · started 30 minutes ago',
    );
    await expect(part(cleanup, '[data-next-row-descriptor]').textContent).toBe(
      'Claude · acme/api · started 2 hours ago · ended 25 minutes ago',
    );
    await expect(part(docs, '[data-next-operation-fact="now"]').textContent).toBe(
      'Running 3 helpers · writing the docs pull request',
    );

    // Blocked is the Waiting on you tile; the question it holds stays on the row, under the Now line.
    const waiting = within(billing);
    await expect(waiting.getByRole('img', { name: 'Waiting on you' })).toBeVisible();
    await expect(part(billing, '[data-next-row-block-note]').textContent).toBe(QUESTION);
    await expect(within(docs).getByRole('img', { name: 'Working' })).toBeVisible();
    await expect(within(cleanup).getByRole('img', { name: 'Ended' })).toBeVisible();

    // No column strip and no Project, Next or Blocked column on any row.
    await expect(canvasElement.querySelector('.next-operations-columns')).toBeNull();
    await expect(
      canvasElement.querySelectorAll(
        '[data-next-operation-fact="where"], [data-next-operation-fact="next"], [data-next-operation-fact="blocked"]',
      ),
    ).toHaveLength(0);
    for (const row of [docs, billing, cleanup]) {
      await expect(row).not.toHaveTextContent(/No pending step published|Blocked|Next/);
    }

    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        for (const row of [docs, billing, cleanup]) {
          const title = part(row, '.next-operation-route');
          const descriptor = part(row, '[data-next-row-descriptor]');
          const now = part(row, '[data-next-operation-fact="now"]');
          await below(title, descriptor);
          await below(descriptor, now);
          await expect(
            Number.parseFloat(getComputedStyle(descriptor).fontSize),
          ).toBeGreaterThanOrEqual(13);
          const goal = part(row, '[data-next-operation-fact="goal"]');
          const identity = part(row, '.next-operation-identity');
          if (width === 1280) {
            // The goal sits to the right of the session, on the same band.
            await expect(goal.getBoundingClientRect().left).toBeGreaterThanOrEqual(
              identity.getBoundingClientRect().right - 1,
            );
            await expect(goal.getBoundingClientRect().top).toBeLessThan(
              identity.getBoundingClientRect().bottom,
            );
          } else {
            // A phone stacks the goal under the session.
            await below(identity, goal);
          }
        }
        await below(
          part(billing, '[data-next-operation-fact="now"]'),
          part(billing, '[data-next-row-block-note]'),
        );
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      });
    }
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};
