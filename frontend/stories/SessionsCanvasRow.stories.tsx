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
                  {
                    harness: 'claude',
                    sid: 'acme-nightly',
                    project: 'acme/website',
                    project_key: '/acme/website',
                    title: 'Nightly dependency check',
                    state: 'idle',
                    started_at: G - 10800,
                    finished_at: G - 180,
                    last_activity: G - 180,
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
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(4),
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

/* The list as the redesign canvas draws it (owner request, 2026-11-24): both groups in one white card, each
   opening with a small header band, history on the card's tinted ground, rows split by hairline dividers and
   no coloured left edge. A history row says its end and git facts once. */
const near = async (actual: number, expected: number, slack = 1) => {
  await expect(actual).toBeGreaterThanOrEqual(expected - slack);
  await expect(actual).toBeLessThanOrEqual(expected + slack);
};

export const ListCard: Story = {
  render: () => <Board />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(4),
    );
    const card = canvasElement.querySelector<HTMLElement>('[data-sessions-list-card]');
    if (!card) throw new Error('Missing the list card');
    const active = part(card, '[data-next-operation-group="active"]');
    const history = part(card, '[data-next-operation-group="history"]');
    const docs = rowOf(canvasElement, 'acme-docs');
    const cleanup = rowOf(canvasElement, 'acme-cleanup');
    const nightly = rowOf(canvasElement, 'acme-nightly');

    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        // One white card wraps both groups.
        await expect(card).toHaveStyle({
          backgroundColor: 'rgb(255, 255, 255)',
          borderTopWidth: '1px',
          borderTopStyle: 'solid',
          borderTopColor: 'rgb(227, 231, 235)',
          borderTopLeftRadius: '16px',
          overflow: 'hidden',
        });
        await expect(card.contains(active) && card.contains(history)).toBe(true);
        await expect(card.getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth);

        // Each group opens with a small header band; history sits under a divider on the tinted ground.
        for (const group of [active, history]) {
          const header = part(group, ':scope > header');
          await expect(part(header, 'h2')).toHaveStyle({
            fontSize: '13px',
            fontWeight: '700',
            color: 'rgb(62, 76, 89)',
          });
          await expect(header.querySelector('[data-sessions-group-count]')).toBeVisible();
          await expect(header.getBoundingClientRect().top).toBeGreaterThanOrEqual(
            group.getBoundingClientRect().top,
          );
        }
        await expect(getComputedStyle(active).backgroundColor).toBe('rgba(0, 0, 0, 0)');
        await expect(history).toHaveStyle({
          backgroundColor: 'rgb(250, 251, 252)',
          borderTopWidth: '1px',
          borderTopColor: 'rgb(227, 231, 235)',
        });
        // How session history works stays in the history header band.
        const why = within(history).getByRole('button', { name: 'How session history works' });
        await below(part(history, ':scope > header'), why);
        await expect(why.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);

        for (const row of canvasElement.querySelectorAll<HTMLElement>(
          'article.next-operation-row',
        )) {
          // Hairline dividers between rows, and no left stripe of any kind.
          await expect(row).toHaveStyle({
            borderTopWidth: '1px',
            borderTopColor: 'rgb(238, 241, 244)',
            borderLeftWidth: '0px',
            boxShadow: 'none',
          });
          const title = part(row, '.next-operation-route');
          const name = part(title, 'strong');
          const descriptor = part(row, '[data-next-row-descriptor]');
          const now = part(row, '[data-next-operation-fact="now"]');
          await expect(name).toHaveStyle({ fontSize: '18px', fontWeight: '700' });
          // The descriptor sits directly under the title, and the Now line 8 px under that.
          const gap = descriptor.getBoundingClientRect().top - title.getBoundingClientRect().bottom;
          await near(gap, 2, 1.5);
          await expect(descriptor).toHaveStyle({ fontSize: '13px', color: 'rgb(82, 96, 109)' });
          await near(
            now.getBoundingClientRect().top - descriptor.getBoundingClientRect().bottom,
            8,
          );
          await expect(now).toHaveStyle({ fontSize: '15px' });
          // The status tile lines up with the title.
          const tile = row.querySelector<HTMLElement>('[data-next-row-state]');
          if (tile)
            await near(tile.getBoundingClientRect().top, title.getBoundingClientRect().top, 4);
          // The row is the 44 px target: a press on its padding opens the session.
          row.scrollIntoView({ block: 'center' });
          const box = row.getBoundingClientRect();
          await expect(box.height).toBeGreaterThanOrEqual(44);
          await near(
            descriptor.getBoundingClientRect().left - box.left,
            width === 1280 ? 24 + 44 + 12 : 16 + 44 + 8,
            4,
          );
          await expect(document.elementFromPoint(box.left + 6, box.top + 6)).toBe(title);
          await near(name.getBoundingClientRect().top - box.top, width === 1280 ? 20 : 16, 3);
        }

        // The goal: a small bold label over plain ink text, underlined only on hover or focus.
        const goal = part(docs, '[data-next-operation-fact="goal"]');
        await expect(part(goal, 'small')).toHaveStyle({ fontSize: '13px', fontWeight: '600' });
        const link = part(goal, 'a');
        await expect(link).toHaveStyle({
          fontSize: '15px',
          fontWeight: '400',
          color: 'rgb(31, 41, 51)',
          textDecorationLine: 'none',
        });
        link.focus();
        await expect(link).toHaveStyle({ textDecorationLine: 'underline', outlineWidth: '2px' });
        link.blur();
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      });
    }

    // History rows say the end and git facts once. A stop keeps its stop and drops the unmeasured git state;
    // an ended row keeps the reported end and the measured clean state, each once.
    await expect(part(nightly, '[data-next-row-outcome]').textContent).toBe('Stop observed');
    await expect(nightly).not.toHaveTextContent(/not measured|Git state/);
    await expect(part(cleanup, '[data-next-operation-fact="now"]').textContent).toBe(
      'Session reported its own end',
    );
    await expect(part(cleanup, '[data-next-row-outcome]').textContent).toBe(
      'Git state reported clean',
    );
    // The end age once in the descriptor, the reported end once in the Now line.
    await expect(cleanup.textContent?.match(/ended/gi)).toHaveLength(1);
    await expect(cleanup.textContent?.match(/own end/g)).toHaveLength(1);
    await expect(cleanup.textContent?.match(/git state/gi)).toHaveLength(1);
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

/* The status segments as the canvas draws them: on a wide screen, one segmented control on a light grey
   track, the chosen segment white with a border and the rest plain words; on a phone, outlined pills with the
   chosen one filled, as Mobile.dc.html does. Every segment keeps a 44 px target and a visible focus ring. */
export const SegmentedControl: Story = {
  render: () => <Board />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const group = await canvas.findByRole('group', { name: 'Session status' });
    await waitFor(() =>
      expect(within(group).getByRole('button', { name: /^All \d/ })).toBeVisible(),
    );
    const segments = within(group).getAllByRole('button');
    const chosen = within(group).getByRole('button', { name: /^All \d/ });
    await expect(chosen).toHaveAttribute('aria-pressed', 'true');
    await atWidth(1280, async () => {
      await expect(group).toHaveStyle({ backgroundColor: 'rgb(238, 241, 244)', paddingTop: '4px' });
      await expect(chosen).toHaveStyle({
        backgroundColor: 'rgb(255, 255, 255)',
        borderTopColor: 'rgb(123, 135, 148)',
        borderTopWidth: '1px',
        fontWeight: '600',
        color: 'rgb(31, 41, 51)',
      });
      for (const segment of segments) {
        await expect(segment.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
        if (segment === chosen || segment.matches(':disabled')) continue;
        await expect(segment).toHaveStyle({
          backgroundColor: 'rgba(0, 0, 0, 0)',
          borderTopColor: 'rgba(0, 0, 0, 0)',
          fontWeight: '500',
        });
      }
      const working = within(group).getByRole('button', { name: /^Working \d/ });
      working.focus();
      await expect(working).toHaveStyle({
        outlineWidth: '2px',
        outlineStyle: 'solid',
        outlineColor: 'rgb(47, 125, 91)',
      });
      working.blur();
    });
    await atWidth(400, async () => {
      await expect(getComputedStyle(group).backgroundColor).toBe('rgba(0, 0, 0, 0)');
      await expect(chosen).toHaveStyle({
        backgroundColor: 'rgb(31, 41, 51)',
        color: 'rgb(255, 255, 255)',
      });
      for (const segment of segments) {
        await expect(segment.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
        if (segment !== chosen && !segment.matches(':disabled'))
          await expect(segment).toHaveStyle({
            backgroundColor: 'rgb(255, 255, 255)',
            borderTopColor: 'rgb(123, 135, 148)',
          });
      }
      await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(400);
    });
    await expect(canvas.getByRole('searchbox', { name: 'Search sessions' })).toHaveAttribute(
      'placeholder',
      'Search by title, goal or project',
    );
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};
