import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
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

const CANVAS_SESSIONS: readonly Record<string, unknown>[] = [
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
];

function Board({
  sessions = CANVAS_SESSIONS,
  annotate = true,
  usage,
  extra,
}: {
  readonly sessions?: readonly Record<string, unknown>[];
  readonly annotate?: boolean;
  readonly usage?: readonly Record<string, unknown>[];
  readonly extra?: Record<string, unknown>;
}) {
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
                annotate,
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
                sessions,
                ...(usage ? { usage } : {}),
                ...extra,
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

/* The allowance leads the Sessions page, under the example invite and above the greeting (owner, 2026-11-24). */
export const AllowanceLeadsThePage: Story = {
  render: () => (
    <Board
      usage={[
        {
          harness: 'codex',
          state: 'ok',
          asOf: G,
          week: { pct: 82, windowSec: 604800, resetAt: G + 400000 },
        },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const allowance = (await canvas.findByRole('heading', { name: 'Your AI allowance' })).closest(
      'section',
    ) as HTMLElement;
    const greeting = await canvas.findByRole('heading', { level: 1 });
    const list = canvasElement.querySelector('[data-sessions-list-card]') as HTMLElement;
    await expect(
      allowance.compareDocumentPosition(greeting) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await expect(
      allowance.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const invite = canvas.queryByText('New to Compass?');
    if (invite)
      await expect(
        invite.compareDocumentPosition(allowance) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
  },
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
          const tile = part(row, '[data-next-row-tile]');
          await near(tile.getBoundingClientRect().top, title.getBoundingClientRect().top, 4);
          // The row is the 44 px target: a press on its padding opens the session.
          row.scrollIntoView({ block: 'center' });
          const box = row.getBoundingClientRect();
          await expect(box.height).toBeGreaterThanOrEqual(44);
          await near(
            descriptor.getBoundingClientRect().left - box.left,
            // The row's padding, the fixed 44 px tile column and the gap after it.
            width === 1280 ? 24 + 44 + 16 : 16 + 44 + 12,
            1,
          );
          await expect(document.elementFromPoint(box.left + 6, box.top + 6)).toBe(title);
          await near(name.getBoundingClientRect().top - box.top, width === 1280 ? 20 : 16, 3);
        }

        // The goal: a small bold label over plain ink text, underlined only on hover or focus.
        const goal = part(docs, '[data-next-operation-fact="goal"]');
        await expect(part(goal, 'small')).toHaveStyle({ fontSize: '13px', fontWeight: '600' });
        const link = part(goal, 'a');
        /* An earlier story file can leave the real pointer where this link now sits, which underlines it;
           park the pointer on the page heading before reading the resting style. */
        if ('__vitest_browser_runner__' in window) {
          const { page } = await import('vitest/browser');
          await page.getByRole('heading', { level: 1 }).hover();
        }
        await expect(link).toHaveStyle({
          fontSize: '15px',
          fontWeight: '400',
          color: 'rgb(31, 41, 51)',
          textDecorationLine: 'none',
        });
        link.focus();
        await expect(link).toHaveStyle({ textDecorationLine: 'underline', outlineWidth: '2px' });
        link.blur();
        // A row with no goal says so in plain quiet text and offers nothing to press (owner, 2026-11-24): the
        // list cannot add a goal, so the reader opens the row and adds it on the session page.
        for (const sid of ['acme-billing', 'acme-cleanup', 'acme-nightly']) {
          const empty = part(rowOf(canvasElement, sid), '[data-next-operation-fact="goal"]');
          const word = part(empty, '[data-next-goal-absent]');
          await expect(word.textContent).toBe('No goal yet');
          await expect(word).toHaveStyle({
            fontSize: '13px',
            color: 'rgb(82, 96, 109)',
            borderTopWidth: '0px',
            backgroundImage: 'none',
          });
          await expect(empty.querySelector('a, button, svg')).toBeNull();
          await expect(rowOf(canvasElement, sid)).not.toHaveTextContent('Add a goal');
          await expect(
            within(rowOf(canvasElement, sid)).queryByRole('link', { name: /goal/i }),
          ).toBeNull();
          await expect(
            within(rowOf(canvasElement, sid)).queryByRole('button', { name: /goal/i }),
          ).toBeNull();
        }
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

/* The grey word at the right of a row (owner, 2026-11-24): Not checked yet where the goal, or the draft a check
   would adopt, has no check recorded, and nothing where the board cannot prove it. No goal yet stays in the
   Goal cell, once. A goal that cannot be read says so and never No goal yet. Invented rows throughout. */
const ABSENT = { annotation_goal: '', annotation_goal_why: 'No goal typed for this session.' };
const ABSENCE_ROUTES = { claude: { reason: '' }, codex: { reason: '' } };
const base = (sid: string, title: string) => ({
  harness: 'claude',
  sid,
  project: 'acme/api',
  project_key: '/acme/api',
  title,
  state: 'idle',
  started_at: G - 3600,
  last_activity: G - 60,
});
const ABSENCE_SESSIONS: readonly Record<string, unknown>[] = [
  {
    ...base('acme-unchecked', 'Draft the release notes'),
    annotation_goal: 'Publish the acme release notes',
    annotation_revision: 1,
  },
  {
    ...base('acme-draft', 'Tidy the invoice export'),
    ...ABSENT,
    first_prompt: 'Tidy the invoice export',
    first_prompt_at: G - 3500,
  },
  { ...base('acme-empty', 'Open question'), ...ABSENT },
  {
    ...base('acme-lines', 'Write the changelog'),
    ...ABSENT,
    annotation_line_1: 'The changelog lists every fix',
  },
  {
    ...base('acme-codex', 'Port the importer'),
    harness: 'codex',
    annotation_goal: 'Port the acme importer',
    annotation_revision: 1,
  },
  {
    ...base('acme-held', 'Rename the tables'),
    annotation_goal: '',
    annotation_goal_why: '',
    annotation_goal_unreadable: true,
    first_prompt: 'Rename the legacy tables',
    first_prompt_at: G - 3500,
  },
];

export const AbsenceWord: Story = {
  render: () => <Board sessions={ABSENCE_SESSIONS} extra={{ reading_routes: ABSENCE_ROUTES }} />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(6),
    );
    const word = (sid: string) =>
      rowOf(canvasElement, sid).querySelector<HTMLElement>('[data-next-row-absence]');
    for (const width of [1280, 700, 400]) {
      await atWidth(width, async () => {
        for (const sid of ['acme-unchecked', 'acme-draft', 'acme-lines']) {
          const row = rowOf(canvasElement, sid);
          const found = word(sid);
          if (!found) throw new Error(`No absence word on ${sid}`);
          await expect(found.textContent).toBe('Not checked yet');
          // Plain quiet text: no pill, border, background, icon or action, and outside the row link.
          await expect(found).toHaveStyle({
            fontSize: '13px',
            color: 'rgb(82, 96, 109)',
            borderTopWidth: '0px',
            borderTopLeftRadius: '0px',
            paddingLeft: '0px',
            backgroundImage: 'none',
            backgroundColor: 'rgba(0, 0, 0, 0)',
          });
          await expect(found.querySelector('svg, img')).toBeNull();
          await expect(found.closest('a, button')).toBeNull();
          await expect(found.className).not.toMatch(/badge|pill/i);
          await expect(found.hasAttribute('data-slot')).toBe(false);
          await expect(row.querySelector('[data-slot="badge"], [data-next-drift-pill]')).toBeNull();
          const goal = part(row, '[data-next-operation-fact="goal"]');
          await expect(goal.contains(found)).toBe(false);
          const box = found.getBoundingClientRect();
          if (width >= 700) {
            // The far right, top-aligned with the title, and the goal beside it is not squeezed away.
            const title = part(row, '.next-operation-route').getBoundingClientRect();
            await near(box.top, title.top, 4);
            await expect(box.left).toBeGreaterThanOrEqual(goal.getBoundingClientRect().right - 1);
            await expect(box.right).toBeLessThanOrEqual(row.getBoundingClientRect().right);
            await expect(goal.getBoundingClientRect().width).toBeGreaterThanOrEqual(150);
          } else {
            // A phone stacks it under the Goal cell, still on the screen.
            await expect(box.top).toBeGreaterThanOrEqual(goal.getBoundingClientRect().bottom - 1);
            await expect(box.right).toBeLessThanOrEqual(window.innerWidth);
          }
          // A press on the word still opens the session: it sits under the card's cover.
          await expect(word(sid)?.textContent).toBe('Not checked yet');
        }
        // Rows with nothing to prove draw no element at all: empty, Codex and unreadable.
        for (const sid of ['acme-empty', 'acme-codex', 'acme-held'])
          await expect(word(sid)).toBeNull();
        // No goal yet is in the Goal cell once, and a draft row shows its prompt instead, never both.
        await expect(
          rowOf(canvasElement, 'acme-empty').textContent?.match(/No goal yet/g),
        ).toHaveLength(1);
        for (const sid of ['acme-draft', 'acme-unchecked', 'acme-lines'])
          await expect(rowOf(canvasElement, sid).textContent).not.toMatch(/No goal yet/);
        // Saved outcome lines and no goal name the expected outcome, never No goal yet beside Not checked yet.
        await expect(
          part(rowOf(canvasElement, 'acme-lines'), '[data-next-operation-fact="goal"]').textContent,
        ).toContain('What "done" looks like');
        // A goal that cannot be read says so, never No goal yet or its prompt.
        const held = rowOf(canvasElement, 'acme-held');
        await expect(part(held, '[data-next-operation-fact="goal"]').textContent).toContain(
          'Saved goal unavailable',
        );
        await expect(held.textContent).not.toMatch(/No goal yet|Not checked yet|legacy tables/);
        await expect(held.querySelector('[data-next-operation-fact="goal"] a')).toBeNull();
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      });
    }
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

/* Both "No goal yet" chips keep exactly the rows whose Goal cell reads it, through one predicate. A draft row
   shows its prompt as a goal a check can adopt, so neither chip keeps it. */
export const NoGoalChips: Story = {
  render: () => <Board sessions={ABSENCE_SESSIONS} extra={{ reading_routes: ABSENCE_ROUTES }} />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(6),
    );
    const shown = () =>
      [...canvasElement.querySelectorAll('article.next-operation-row')]
        .map((row) => row.getAttribute('data-next-session'))
        .sort();
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Filters' }));
    const panel = within(canvas.getByRole('region', { name: 'Filters' }));
    const progress = within(panel.getByRole('group', { name: 'Progress check' }));
    const chip = progress.getByRole('button', { name: 'No goal yet' });
    await userEvent.click(chip);
    await waitFor(() => expect(shown()).toEqual(['acme-empty']));
    const kept = shown() as string[];
    for (const sid of kept)
      await expect(
        part(rowOf(canvasElement, sid), '[data-next-operation-fact="goal"]').textContent,
      ).toContain('No goal yet');
    await userEvent.click(chip);
    await userEvent.click(panel.getByRole('button', { name: 'More filters for power users' }));
    const goal = canvasElement.querySelector<HTMLElement>('[data-filter-facet="goal"]');
    if (!goal) throw new Error('Missing the goal facet');
    await userEvent.click(within(goal).getByText('No goal yet'));
    await waitFor(() => expect(shown()).toEqual(kept));
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

/* Every row draws a tile, and the tile column is a fixed 44 px slot, so every title starts at the same x
   (owner, 2026-11-24). A session whose state is not published shows the neutral State not known tile; one
   waiting on a declared child shows its own state's tile and keeps the Waiting on child line. */
const TILE_SESSIONS: readonly Record<string, unknown>[] = [
  ...CANVAS_SESSIONS,
  {
    harness: 'claude',
    sid: 'acme-lint',
    project: 'acme/website',
    project_key: '/acme/website',
    title: 'Fix the lint warnings',
    state: 'idle',
    started_at: G - 3600,
    last_activity: G - 60,
  },
  {
    harness: 'claude',
    sid: 'acme-release',
    project: 'acme/api',
    project_key: '/acme/api',
    title: 'Coordinate the api release',
    state: 'working',
    active: true,
    waiting_on_child: { harness: 'claude', sid: 'acme-docs' },
    started_at: G - 2400,
    last_activity: G - 30,
  },
  {
    harness: 'claude',
    sid: 'acme-review',
    project: 'acme/api',
    project_key: '/acme/api',
    title: 'Review the api changes',
    state: 'idle',
    finished_at: G - 90,
    waiting_on_child: { harness: 'claude', sid: 'acme-docs' },
    started_at: G - 2000,
    last_activity: G - 90,
  },
  {
    harness: 'claude',
    sid: 'acme-untitled',
    project: 'acme/website',
    project_key: '/acme/website',
    state: 'working',
    active: true,
    state_detail: 'Editing the footer',
    started_at: G - 900,
    last_activity: G - 20,
  },
  {
    harness: 'claude',
    sid: 'acme-audit',
    project: 'acme/api',
    project_key: '/acme/api',
    title: 'Audit the api keys',
    state: 'idle',
    waiting_on_child: { harness: 'claude', sid: 'acme-docs' },
    started_at: G - 2200,
    last_activity: G - 100,
  },
];

export const TileColumn: Story = {
  render: () => <Board sessions={TILE_SESSIONS} />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(
        TILE_SESSIONS.length,
      ),
    );
    const tileOf = (sid: string) => part(rowOf(canvasElement, sid), '[data-next-row-tile]');

    // A state that is not published draws the neutral tile, named for what Compass can say.
    const lint = rowOf(canvasElement, 'acme-lint');
    const unknown = within(lint).getByRole('img', { name: 'State not known' });
    await expect(unknown.querySelector('[data-icon="state-not-known"]')).not.toBeNull();
    await expect(lint).toHaveTextContent('State not published');
    // A child wait shows the session's own state's tile, or the neutral one, and keeps its line.
    for (const [sid, tile] of [
      ['acme-release', 'Working'],
      ['acme-review', 'Quiet'],
      ['acme-audit', 'State not known'],
    ] as const) {
      const row = rowOf(canvasElement, sid);
      await expect(within(row).getByRole('img', { name: tile })).toBe(tileOf(sid));
      await expect(row).toHaveTextContent('Waiting on child "Write the dashboard docs"');
    }
    // An unknown title is a calm absence: the title's size in quiet ink, no hatch, dashed edge or box, and
    // still the row's link (owner, 2026-11-24).
    const untitled = rowOf(canvasElement, 'acme-untitled');
    const missing = part(untitled, '.next-operation-route strong');
    await expect(missing.textContent).toBe('Title not published');
    await expect(missing).toHaveStyle({
      fontSize: '18px',
      fontWeight: '600',
      color: 'rgb(82, 96, 109)',
      backgroundImage: 'none',
      backgroundColor: 'rgba(0, 0, 0, 0)',
      borderTopWidth: '0px',
      borderLeftWidth: '0px',
      paddingTop: '0px',
      paddingLeft: '0px',
    });
    await expect(missing.classList.contains('next-absence')).toBe(false);
    await expect(
      within(untitled).getByRole('link', { name: 'Open session Title not published' }),
    ).toBeVisible();
    // The neutral tile is grey: quiet ink on the page ground, distinct from Quiet's pair.
    await expect(part(unknown, ':scope > span')).toHaveStyle({
      backgroundColor: 'rgb(244, 246, 248)',
      color: 'rgb(82, 96, 109)',
    });

    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        const rows = [...canvasElement.querySelectorAll<HTMLElement>('article.next-operation-row')];
        const kinds = new Set(
          rows.map((row) => part(row, '[data-next-row-tile]').dataset['nextRowTile']),
        );
        await expect([...kinds].sort()).toEqual(
          ['Ended', 'Quiet', 'State not known', 'Waiting on you', 'Working'].sort(),
        );
        const lefts = rows.map((row) => ({
          title: part(row, '.next-operation-route').getBoundingClientRect().left,
          descriptor: part(row, '[data-next-row-descriptor]').getBoundingClientRect().left,
          now: part(row, '[data-next-operation-fact="now"]').getBoundingClientRect().left,
          slot: part(row, '[data-next-row-tile-slot]').getBoundingClientRect(),
        }));
        const first = lefts[0];
        if (!first) throw new Error('No rows');
        for (const left of lefts) {
          await expect(left.title).toBeCloseTo(first.title, 0);
          await expect(left.descriptor).toBeCloseTo(first.title, 0);
          await expect(left.now).toBeCloseTo(first.title, 0);
          await expect(left.slot.width).toBe(44);
        }
        for (const row of rows) {
          const tile = part(row, '[data-next-row-tile]').getBoundingClientRect();
          await expect(tile.width).toBeGreaterThanOrEqual(44);
          await expect(tile.height).toBeGreaterThanOrEqual(44);
        }
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      });
    }

    // The legend names the new tile beside the four states and the flag.
    const legend = within(canvasElement).getByRole('list', { name: 'What the icons mean' });
    const entries = within(legend)
      .getAllByRole('listitem')
      .map((item) => item.textContent);
    await expect(entries).toEqual([
      'Working',
      'Waiting on you',
      'Quiet',
      'Ended',
      'State not known',
      'Worth a look',
    ]);
    await expect(legend.querySelector('[data-icon="state-not-known"]')).not.toBeNull();
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

/* An empty group, and a group the filters empty, say so in plain quiet text padded as a row inside the list
   card: no hatch, dashed edge or tinted box (owner, 2026-11-24). */
const calmLine = async (line: HTMLElement) => {
  await expect(line).toHaveStyle({
    color: 'rgb(82, 96, 109)',
    backgroundImage: 'none',
    backgroundColor: 'rgba(0, 0, 0, 0)',
    borderTopStyle: 'solid',
    borderTopColor: 'rgb(238, 241, 244)',
    borderBottomWidth: '0px',
    borderLeftWidth: '0px',
    borderRightWidth: '0px',
  });
  await expect(Number.parseFloat(getComputedStyle(line).fontSize)).toBeGreaterThanOrEqual(13);
  await expect(line.classList.contains('next-absence')).toBe(false);
};
const ONLY_HISTORY = CANVAS_SESSIONS.filter((session) => session['sid'] === 'acme-cleanup');
const ONLY_ACTIVE = CANVAS_SESSIONS.filter((session) => session['sid'] === 'acme-docs');

export const EmptyRightNow: Story = {
  render: () => <Board sessions={ONLY_HISTORY} />,
  play: async ({ canvasElement }) => {
    const line = await waitFor(() => part(canvasElement, '[data-next-sessions-empty="active"]'));
    await expect(line.textContent).toBe('No exact session has active evidence right now.');
    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        await calmLine(line);
        // Padded as a row: the text starts where a row's title block does.
        const row = rowOf(canvasElement, 'acme-cleanup');
        await expect(getComputedStyle(line).paddingLeft).toBe(getComputedStyle(row).paddingLeft);
        await expect(getComputedStyle(line).paddingTop).toBe(getComputedStyle(row).paddingTop);
        await expect(line.getBoundingClientRect().right).toBeLessThanOrEqual(
          part(canvasElement, '[data-sessions-list-card]').getBoundingClientRect().right,
        );
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
      });
    }
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

export const EmptyHistoryAndFiltered: Story = {
  render: () => <Board sessions={[...ONLY_ACTIVE, ...ONLY_HISTORY]} />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(2),
    );
    const search = within(canvasElement).getByRole('searchbox', { name: 'Search sessions' });
    await userEvent.type(search, 'feature flags');
    const filtered = await waitFor(() =>
      part(canvasElement, '[data-next-sessions-filtered-empty]'),
    );
    await expect(filtered.textContent).toBe(
      'The 1 session in Right now does not match these filters.',
    );
    for (const width of [1280, 400]) await atWidth(width, () => calmLine(filtered));
    await userEvent.clear(search);
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-sessions-filtered-empty]')).toBeNull(),
    );
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

export const EmptyHistory: Story = {
  render: () => <Board sessions={ONLY_ACTIVE} />,
  play: async ({ canvasElement }) => {
    const line = await waitFor(() => part(canvasElement, '[data-next-sessions-empty="history"]'));
    await expect(line.textContent).toBe('No recent-history rows in this payload.');
    for (const width of [1280, 400]) await atWidth(width, () => calmLine(line));
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

/* With annotations off the goal cell says so in plain quiet text, as No goal yet is drawn, with no hatch or
   dashed box (owner, 2026-11-24). */
export const AnnotationsOffGoal: Story = {
  render: () => <Board annotate={false} />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('article.next-operation-row')).toHaveLength(4),
    );
    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        for (const row of canvasElement.querySelectorAll<HTMLElement>(
          'article.next-operation-row',
        )) {
          const value = part(row, '[data-next-operation-fact="goal"] strong');
          await expect(value.textContent).toBe('Annotations off');
          await expect(value).toHaveStyle({
            fontSize: '13px',
            color: 'rgb(82, 96, 109)',
            backgroundImage: 'none',
            borderTopWidth: '0px',
            paddingLeft: '0px',
          });
          await expect(value.classList.contains('next-absence')).toBe(false);
        }
      });
    }
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

/* The search field and the Filters button beside it share one radius token, and All sessions sits at the
   canvas's section-title step (owner, 2026-11-24). */
export const SearchToolbar: Story = {
  render: () => <Board />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const search = await canvas.findByRole('searchbox', { name: 'Search sessions' });
    const filters = canvas.getByRole('button', { name: 'Filters' });
    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        const field = getComputedStyle(search);
        const button = getComputedStyle(filters);
        await expect(field.borderTopLeftRadius).toBe(button.borderTopLeftRadius);
        await expect(field.borderBottomRightRadius).toBe(button.borderBottomRightRadius);
        await expect(Number.parseFloat(field.borderTopLeftRadius)).toBeGreaterThan(4);
      });
    }
    // A phone hides the heading, as Mobile.dc.html does; a wide screen draws it at 24 px, 700.
    await atWidth(1280, () =>
      expect(canvas.getByRole('heading', { name: 'All sessions' })).toHaveStyle({
        fontSize: '24px',
        fontWeight: '700',
      }),
    );
  },
};
