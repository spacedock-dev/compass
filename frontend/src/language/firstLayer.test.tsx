import { fireEvent, render, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import states from '../../test/fixtures/client-contract/data-session-states.json';
import focused from '../../test/fixtures/client-contract/data-focused-drift.json';
import { fragmentForRoute } from '../router/grammar';
import { mountShell } from '../shell/testing';
import { boardCopyViolations, firstLayerViolations } from '../../test/firstLayer';
import { FIRST_LAYER_RETIREMENTS } from './glossary';

// Add later pages here with their recorded client-contract board and a route that reaches the view.
it.each([states, focused])(
  'keeps Compass copy on Sessions and the Session page current over $name',
  async ({ response }) => {
    const data = response.body;
    const page = mountShell({ data });
    await page.settle();
    expect(
      within(page.container).getByRole('link', { name: 'Sessions', current: 'page' }),
    ).toBeVisible();
    expect(boardCopyViolations(page.container)).toEqual([]);
    for (const row of data.sessions) {
      if (!row.sid || !row.harness) continue;
      await page.go(
        fragmentForRoute({
          view: 'session',
          project: row.project ?? '',
          harness: row.harness,
          session: row.sid,
        }),
      );
      const article = page.container.querySelector('[data-next-session-detail]');
      expect(article, row.sid).not.toBeNull();
      expect(boardCopyViolations(page.container), row.sid).toEqual([]);
    }
  },
);

it.each([
  {
    name: 'Needs you',
    hash: '#n=attention',
    heading: 'Needs you',
    disclosure: "What Compass can't see",
  },
  {
    name: 'Goal history',
    hash: '#n=intent',
    heading: 'Goal history',
    disclosure: 'How long goals are kept',
  },
  { name: 'Help', hash: '#n=help', heading: 'How Compass works' },
  { name: 'Projects', hash: '#n=projects', heading: 'Projects', link: /alpha-app/ },
  { name: 'project Overview', hash: '#n=project:alpha-app', heading: 'alpha-app', tab: 'Overview' },
  {
    name: 'project Timeline',
    hash: '#n=project:alpha-app:course',
    heading: 'alpha-app',
    tab: 'Timeline',
  },
  {
    name: 'project Decisions',
    hash: '#n=project:alpha-app:decisions',
    heading: 'alpha-app',
    tab: 'Decisions',
  },
  {
    name: 'project Usage and alerts',
    hash: '#n=project:alpha-app:console',
    heading: 'alpha-app',
    tab: 'Usage and alerts',
  },
  { name: 'Settings', hash: '#n=settings', heading: 'Settings' },
])('keeps Compass copy on $name current', async ({ hash, heading, link, tab, disclosure }) => {
  const page = mountShell({ hash, data: states.response.body });
  await page.settle();
  const view = within(page.container);
  expect(view.getByRole('heading', { name: heading, level: 1 })).toBeVisible();
  if (link) expect(view.getAllByRole('link', { name: link })[0]).toBeVisible();
  if (tab) expect(view.getByRole('tab', { name: new RegExp(tab), selected: true })).toBeVisible();
  expect(boardCopyViolations(page.container)).toEqual([]);
  if (disclosure) {
    const trigger = view.getByRole('button', { name: disclosure });
    fireEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(boardCopyViolations(page.container)).toEqual([]);
  }
});

it('keeps Compass copy in the Settings disclosures current', async () => {
  const limits = [
    { key: 'analyze_prompt_bytes', default: 524288, minimum: 16384, maximum: 2097152 },
    { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 20000 },
    { key: 'analyze_listed_checks', default: 1000, minimum: 12, maximum: 5000 },
    { key: 'analyze_scan_megabytes', default: 512, minimum: 8, maximum: 1024 },
  ];
  const page = mountShell({
    hash: '#n=settings',
    data: states.response.body,
    getResponses: {
      '/api/settings': {
        limits,
        values: Object.fromEntries(limits.map((limit) => [limit.key, limit.default])),
        update_check: { disabled: false, default_enabled: true, cli_disabled: false },
        store_readable: true,
      },
      '/api/health': { port: 6237 },
    },
  });
  await page.settle();

  const view = within(page.container);
  const yourData = within(view.getByRole('region', { name: 'Your data' }));
  fireEvent.click(yourData.getByRole('button', { name: 'Forget everything' }));
  fireEvent.click(view.getByRole('button', { name: 'What is sent, and where' }));
  fireEvent.click(view.getByRole('button', { name: 'Customize' }));
  expect(yourData.getByText('This cannot be undone.')).toBeVisible();
  expect(yourData.getByRole('button', { name: 'Copy' })).toBeVisible();
  expect(view.getByText('Saved prompt size limit: 512 KB.')).toBeVisible();
  expect(view.getByRole('slider', { name: 'Prompt size' })).toBeVisible();
  expect(boardCopyViolations(page.container)).toEqual([]);
});

it('keeps Compass copy on the example invitation current', async () => {
  const page = mountShell({ data: states.response.body });
  await page.settle();
  const invite = page.container.querySelector('[data-sample-invite]');
  expect(invite).not.toBeNull();
  if (!invite) throw new Error('The example invitation did not render');
  expect(within(invite as HTMLElement).getByRole('link', { name: 'See an example' })).toBeVisible();
  expect(within(invite as HTMLElement).getByRole('button', { name: 'Not now' })).toBeVisible();
  expect(boardCopyViolations(invite)).toEqual([]);
});

it('names the text, attribute and element for planted Compass copy', () => {
  const { container } = render(
    <div>
      <h2 id="planted-label">Intent</h2>
      <button type="button" aria-label="Analyze drift">
        Read
      </button>
      <p title="Pause model calls">Pause</p>
      <input placeholder="Mark as inaccurate" />
    </div>,
  );
  expect(firstLayerViolations(container)).toEqual([
    '<h2 id="planted-label"> text "Intent"',
    '<button> aria-label "Analyze drift"',
    '<p> title "Pause model calls"',
    '<input> placeholder "Mark as inaccurate"',
  ]);
});

it('allows authored words, technical evidence, product names and pull request numbers', () => {
  const { container } = render(
    <div>
      <h2 data-authored title="Intent">
        Intent for a drift check
      </h2>
      <blockquote data-authored>
        <span aria-label="Intent">Compare drift</span>
      </blockquote>
      <section data-layer="technical">
        <p>Live monitor · Haiku · revision 2 · entry #8 · [7]</p>
      </section>
      <p title="Claude Code">Review #482 in Claude Code</p>
    </div>,
  );
  expect(firstLayerViolations(container)).toEqual([]);
});

it('allows the same wording in the mounted session title and goal', async () => {
  const board = states.response.body;
  const one = board.sessions[0];
  if (!one) throw new Error('The recorded board has no session');
  const title = 'Intent and drift for #482';
  const goal = 'Trace drift in the Intent parser';
  const page = mountShell({
    hash: fragmentForRoute({
      view: 'session',
      project: one.project ?? '',
      harness: one.harness,
      session: one.sid,
    }),
    data: {
      ...board,
      sessions: [
        {
          ...one,
          title,
          annotation_goal: goal,
          annotation_revision: 1,
          annotation_at: board.generated - 60,
        },
      ],
    },
  });
  await page.settle();
  const view = within(page.container);
  expect(view.getByRole('heading', { name: title })).toBeVisible();
  expect(view.getByText(goal)).toBeVisible();
  expect(firstLayerViolations(page.container)).toEqual([]);
});

it('applies a retirement added to the glossary rules without a change to the walk', () => {
  const { container } = render(<button type="button">Legacy action</button>);
  expect(firstLayerViolations(container)).toEqual([]);
  expect(
    firstLayerViolations(container, [...FIRST_LAYER_RETIREMENTS, /\blegacy action\b/i]),
  ).toEqual(['<button> text "Legacy action"']);
});

it('catches ruled labels in context, including a phrase split by inline markup', () => {
  const { container } = render(
    <>
      <h3>Not enough recorded yet</h3>
      <button type="button" aria-label="Session state: Idle" title="Progress level: High">
        Analyze
      </button>
      <input placeholder="Check again to update" />
      <p>
        Pause <b>model calls</b>
      </p>
      <p>Harness does not report blocks</p>
      <p>Idle (3)</p>
      <p>Medium so far</p>
      <p>No subagents</p>
      <p>Departure · Goal</p>
      <p>Active now</p>
      <p>At risk</p>
      <p>Not checked yet</p>
      <p>High contrast</p>
    </>,
  );
  expect(firstLayerViolations(container)).toEqual([
    '<h3> text "Not enough recorded yet"',
    '<button> aria-label "Session state: Idle"',
    '<button> title "Progress level: High"',
    '<button> text "Analyze"',
    '<input> placeholder "Check again to update"',
    '<p> text "Pause model calls"',
    '<p> text "Harness does not report blocks"',
    '<p> text "Idle (3)"',
    '<p> text "Medium so far"',
    '<p> text "No subagents"',
    '<p> text "Departure · Goal"',
    '<p> text "Active now"',
    '<p> text "At risk"',
  ]);
});
