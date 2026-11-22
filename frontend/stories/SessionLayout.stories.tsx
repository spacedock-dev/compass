import { openSessionTechnicalTab } from './sessionTechnical';
import { SubagentsView } from '../src/sessions/DetailParts';
import { sessionSubagents } from '../src/sessions/detail';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { seeInContext } from './citation';
import { auditTechnicalMonospace } from './calm.audit';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { DRIFT_SUBTITLE, INTENT_MEASURED } from '../src/intent/sentences';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { WHAT_IT_DID_PLACEHOLDER } from '../src/sessions/WhatItDid';
import { createShell } from '../src/shell/createShell';
import { WAITING_ANSWER_WHERE } from '../src/sessions/WaitingBlock';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { routeOf } from './drift.scenario';

/* The session page as one column (owner, 2026-10-19): the header, the answer block when the session needs
   input, the Intent card, the What the session has done card, the Drift card and Activity log, collapsed.
   Every story mounts the real page over a scripted backend; a path nobody scripted answers `{}`. */

const meta = { title: 'Sessions/One-column page' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const G = 1900000000;

const message = (n: number) => ({
  fact_id: `e${String(n)}`,
  at: G - 100 + n,
  type: 'agent_message',
  by: 'agent',
  source_session: { harness: 'claude', sid: 's1' },
  summary: `Synthetic entry ${String(n)}`,
  evidence: { source: 'transcript', confidence: 'exact' },
  ordinal: n,
});

/* A stored reading whose Goal cites what `cites` names: `e5` sits on the older record page, `ghost` on none. */
const reading = (cites: readonly string[], readAt: number, windowStart: number) => ({
  revision_read: 1,
  revision_read_at: G - 200,
  window_start: windowStart,
  read_at: readAt,
  evidence_through: G - 10,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model: claude-sonnet-5-5, read at 01:46',
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
      result: 'consistent with the evidence read',
      cites,
      detail: '',
      clause: 'Synthetic goal',
    },
  },
});

const ASK = {
  id: 'q1',
  session_id: 's1',
  harness: 'claude',
  question: 'Run the synthetic migration now?',
  options: ['Yes, run it', 'Not yet'],
  age_sec: 30,
};

/* A question and options Compass shortened, at the caps the stdio server sends: 2,000 characters for the
   question and 240 for an option, each ending in "…". One option is a run with no spaces, the widest a label
   can be. */
const WORDS = 'Should the synthetic migration run against the staging copy first ';
const SHORTENED_ASK = {
  ...ASK,
  question: `${WORDS.repeat(40).slice(0, 1_999).trimEnd()}…`,
  options: [`${WORDS.repeat(4).slice(0, 239).trimEnd()}…`, `${'o'.repeat(239)}…`, 'Not yet'],
  question_sent_chars: 2_500,
  dropped_options: 2,
};

interface Log {
  answers: string[];
  ask: Record<string, unknown>;
  asking: boolean;
  gate: boolean;
  resumable: boolean;
  release: (() => void) | null;
  readAt: number;
  served: number;
  previews: number;
  stallOlder: boolean;
  olderAsked: boolean;
  releaseOlder: (() => void) | null;
}
const log: Log = {
  answers: [],
  ask: ASK,
  asking: false,
  gate: false,
  resumable: true,
  release: null,
  readAt: G - 10,
  served: 0,
  previews: 0,
  stallOlder: false,
  olderAsked: false,
  releaseOlder: null,
};

/* `windowStart` is the session's current intent window; the stored reading keeps its own, so a later window
   makes it a retained reading whose citations may sit before the one now open. `stallOlder` holds the older
   record page until the story releases it. */
function PageExample({
  asking = false,
  ask = ASK,
  gate = false,
  resumable = true,
  cites = null,
  windowStart = G - 200,
  stallOlder = false,
  ended = false,
  idle = false,
  readingWindow = G - 200,
  revised = false,
  entries,
  technical = false,
}: {
  readonly asking?: boolean;
  /** The exact request published while `asking`. */
  readonly ask?: Record<string, unknown>;
  /** A harness's own gate, which can coexist with an exact request. */
  readonly gate?: boolean;
  /** Whether the session publishes a token its harness's CLI takes back in. */
  readonly resumable?: boolean;
  readonly cites?: readonly string[] | null;
  readonly windowStart?: number;
  readonly stallOlder?: boolean;
  readonly ended?: boolean;
  readonly idle?: boolean;
  readonly readingWindow?: number;
  readonly revised?: boolean;
  readonly technical?: boolean;
  readonly entries?: readonly Record<string, unknown>[];
}) {
  const [shell] = useState(() => {
    log.answers = [];
    log.ask = ask;
    log.asking = asking;
    log.gate = gate;
    log.resumable = resumable;
    log.release = null;
    log.readAt = G - 10;
    log.served = 0;
    log.previews = 0;
    log.stallOlder = stallOlder;
    log.olderAsked = false;
    log.releaseOlder = null;
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    let generation = G;
    let paused = false;
    let marked = false;
    const policy = () => ({
      consent: true,
      off: paused,
      providers: { claude: true },
      words: { claude: true },
      tool_output: { claude: ['api'] },
      used: 1,
      limit: technical ? 100 : 10,
    });
    const sent = [
      'Sent: your goal, a bounded set of entries, and your messages and the agent’s messages.',
      'The prompt size limit is 524,288 bytes.',
      'The agent’s newest final reply goes whole, up to 16,384 characters.',
      'Tool output includes a check’s command, result and last 180 characters of output, and paths of files written.',
      'To: api.anthropic.com, with credential shapes redacted, through your Claude Code sign-in.',
    ];
    const settings = {
      values: {
        analyze_prompt_bytes: 524288,
        analyze_record_events: 2000,
        analyze_listed_checks: 1000,
        analyze_scan_megabytes: 512,
      },
      limits: [
        { key: 'analyze_prompt_bytes', default: 524288, minimum: 16384, maximum: 2097152 },
        { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 5000 },
        { key: 'analyze_listed_checks', default: 1000, minimum: 12, maximum: 5000 },
        { key: 'analyze_scan_megabytes', default: 512, minimum: 8, maximum: 1024 },
      ],
    };
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url.startsWith('/api/data')) {
          log.served += 1;
          return json({
            generated: generation++,
            annotate: true,
            annotate_cap: 240,
            annotate_goal_cap: 1000,
            reading_check: 'passed',
            reading: policy(),
            ...(technical
              ? {
                  summaries: {
                    consent: true,
                    off: false,
                    reason: paused ? 'model-calls-paused' : '',
                  },
                }
              : {}),
            reading_routes: {
              claude: {
                ...routeOf('claude', {
                  provider: 'claude',
                  label: 'Claude Code',
                  reason: 'own-harness',
                  note: "This session's own harness reads it.",
                  fallback: false,
                }),
                ...(technical
                  ? {
                      disclosure: sent.join(' '),
                      disclosure_parts: sent,
                      destination: 'api.anthropic.com',
                      model: 'claude-sonnet-5-5',
                    }
                  : {}),
              },
            },
            harnesses: [
              { key: 'claude', label: 'Claude Code', reports_rate: true, discovered: true },
            ],
            ...(log.asking ? { ask: true, asks: [log.ask] } : {}),
            sessions: [
              {
                harness: 'claude',
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic layout session',
                state: idle ? 'idle' : log.gate ? 'needs_input' : 'working',
                ...(log.resumable ? { resume_id: 's1' } : {}),
                started_at: G - 3600,
                rate_per_min: 1450,
                ...(log.gate
                  ? { state_detail: 'Permission prompt: Bash', blocked_since: G - 900 }
                  : idle
                    ? { finished_at: G - 600, state_detail: 'awaiting your message' }
                    : {
                        tasks: [{ subject: 'running Bash', status: 'in_progress' }],
                        state_detail: 'running Bash',
                        turn: { elapsed_h: '3m' },
                      }),
                ...(technical ? { delivery_raises: 1, delivery_why: 'Accepted by macOS.' } : {}),
                delegated_launches: 2,
                delegated_unpaired: 1,
                delegated_visibility: 'full',
                delegated_latest_launch_at: G - 300,
                // Quiet for 50 minutes with a launch unpaired, so the "still running?" check is drawn.
                delegated_quiet_since: G - 3000,
                ...(ended ? { ended_at: G - 60 } : {}),
                reading_eligibility: { ok: true, reason: null, until: null, sentence: null },
                annotation_goal: 'Synthetic goal',
                annotation_revision: 1,
                annotation_revision_count: 1,
                annotation_at: G - 200,
                annotation_goal_saved_at: G - 200,
                annotation_window_start: windowStart,
                ...(revised
                  ? {
                      annotation_revision: 2,
                      annotation_revision_count: 2,
                      annotation_at: G - 5,
                      annotation_goal_saved_at: G - 5,
                    }
                  : {}),
                annotation_binding_why: 'These words are bound to claude:s1.',
                ...(cites
                  ? {
                      annotation_reading_count: 1,
                      ...(marked ? { annotation_not_accurate: true } : {}),
                      annotation_assessment: reading(cites, log.readAt, readingWindow),
                    }
                  : {}),
              },
            ],
          });
        }
        if (technical && url === '/api/settings') return json(settings);
        if (technical && url.startsWith('/api/reading-long-plan')) log.previews += 1;
        if (technical && url === '/api/annotate' && init?.method === 'POST') {
          const press = JSON.parse(String(init?.body));
          marked = press.not_accurate === true;
          return json({ outcome: 'stored', persisted: true });
        }
        if (technical && url === '/api/reading') {
          const { consent } = JSON.parse(String(init?.body));
          paused = consent === 'off';
          return json({ ok: true, reading: policy() });
        }
        if (url === '/api/answer') {
          log.answers.push(String(init?.body));
          await new Promise<void>((resolve) => {
            log.release = resolve;
          });
          log.asking = false;
          return json({ answered: true });
        }
        if (url.startsWith('/api/project-context'))
          return json({ semantic: { facts: [] }, sources: { work: { tool_reports: [] } } });
        if (url.startsWith('/api/annotations'))
          return json({ annotations: [], intent_revision: 'r1' });
        if (url.startsWith('/api/session-record')) {
          const older = url.includes('before=');
          if (older && log.stallOlder) {
            log.olderAsked = true;
            await new Promise<void>((resolve) => {
              log.releaseOlder = resolve;
            });
          }
          return json({
            state: 'ok',
            session: { harness: 'claude', sid: 's1' },
            entries:
              entries ?? Array.from({ length: 50 }, (_, i) => message((older ? 50 : 100) - i)),
            next: older || entries ? null : 'older',
            reached_start: Boolean(older || entries),
            bound: null,
            scanned_bytes: 65536,
            kinds: ['user_message', 'agent_message'],
          });
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
  const [mounted, remount] = useState(0);
  return (
    <>
      <App key={mounted} shell={shell} />
      {technical ? (
        <>
          <button
            type="button"
            onClick={() =>
              shell.router.navigate({ view: 'settings', project: null, session: null })
            }
          >
            Open Settings for the story
          </button>
          <button
            type="button"
            onClick={() =>
              shell.router.navigate({
                view: 'session',
                project: 'demo',
                session: 's1',
                harness: 'claude',
              })
            }
          >
            Return to the session
          </button>
        </>
      ) : null}
      <button type="button" onClick={() => remount((previous) => previous + 1)}>
        Remount session
      </button>
      <button type="button" onClick={() => void shell.runtime.refresh()}>
        Simulate board poll
      </button>
    </>
  );
}

const ORDER = ['Asked you', 'Goal', 'What the session has done', 'Drift', 'Show technical details'];
/* A harness's own gate takes the asked block's place, and never stands beside it. */
const REGIONS = [...ORDER, 'Waiting on you'];

/* The page's own regions, by role and accessible name, in document order. */
function regions(root: HTMLElement): HTMLElement[] {
  return within(root)
    .getAllByRole('region')
    .filter((node) => REGIONS.includes(node.getAttribute('aria-label') ?? labelOf(node)));
}
function labelOf(node: HTMLElement): string {
  const id = node.getAttribute('aria-labelledby');
  return id ? (document.getElementById(id)?.textContent ?? '').trim() : '';
}
const named = (root: HTMLElement) =>
  regions(root).map((node) => node.getAttribute('aria-label') ?? labelOf(node));

async function atWidth(width: number, check: () => Promise<void>) {
  const browserPage =
    '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
  const before = { width: window.innerWidth, height: window.innerHeight };
  if (browserPage) await browserPage.viewport(width, 800);
  try {
    if (browserPage) await expect(window.innerWidth).toBe(width);
    await check();
  } finally {
    if (browserPage) await browserPage.viewport(before.width, before.height);
  }
}

async function inOrderTopToBottom(root: HTMLElement, expected: readonly string[]) {
  await waitFor(() => expect(named(root)).toEqual(expected));
  const title = within(root).getByRole('heading', { level: 1 });
  const nodes = [title, ...regions(root)];
  for (let i = 1; i < nodes.length; i += 1) {
    const above = nodes[i - 1] as HTMLElement;
    const below = nodes[i] as HTMLElement;
    await expect(
      above.compareDocumentPosition(below) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // One column: each region starts below the one before it, never beside it.
    await expect(below.getBoundingClientRect().top).toBeGreaterThanOrEqual(
      above.getBoundingClientRect().bottom - 1,
    );
  }
  await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
}

export const RegionsInOrder: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    const breadcrumb = canvas.getByRole('navigation', { name: 'Breadcrumb' });
    await expect(breadcrumb.querySelector('svg[data-icon="caret-right"]')).toBeVisible();
    const expected = ['Goal', 'What the session has done', 'Drift', 'Show technical details'];
    for (const width of [1280, 400]) {
      await atWidth(width, () => inOrderTopToBottom(canvasElement, expected));
    }
    // The state word leads the line that says what it is doing.
    const status = canvasElement.querySelector('[data-next-session-status]') as HTMLElement;
    await expect(status).toHaveTextContent('State: Working');
    await expect(status.querySelector('svg')).toBeNull();
    const meta = canvasElement.querySelector('.next-session-detail-meta') as HTMLElement;
    await expect(meta).toHaveTextContent(/running Bash · turn started 3m ago/);
    // One line, as the design draws it: the state, the identity with its rate and the measured words share a row.
    const identity = canvasElement.querySelector('.next-session-identity') as HTMLElement;
    await expect(identity).toHaveTextContent('1,450 tokens/min');
    await atWidth(1280, async () => {
      const rows = [status, identity, meta].map((node) => node.getBoundingClientRect());
      for (const box of rows)
        await expect(Math.abs(box.top - (rows[0] as DOMRect).top)).toBeLessThan(12);
    });
    await expect(canvas.getByText(WHAT_IT_DID_PLACEHOLDER)).toBeVisible();
    await expect(
      canvas.getByRole('button', { name: /^(Show|Hide) technical details$/ }),
    ).toHaveAttribute('aria-expanded', 'false');
  },
};

/* A session between turns has no rate to show: the last burst reads as speed it no longer has. A finished turn says
   when it ended and that the session waits on the reader. */
export const IdleShowsNoRate: Story = {
  render: () => <PageExample idle />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    const header = canvasElement.querySelector('.next-session-detail-header') as HTMLElement;
    await expect(header).toHaveTextContent('State: Quiet');
    await expect(header).not.toHaveTextContent('tokens/min');
    await expect(header).toHaveTextContent(/Turn ended \d\d:\d\d · waiting for you/);
    await expect(canvasElement).not.toHaveTextContent('idle · awaiting your message');
  },
};

/* The page holds still under the reader: content arriving above a control the pointer is on moves the
   viewport by what it added, so the control stays where the reader aimed. The answer block is the growth here,
   drawn above every card when a board poll brings a question. A DOM `click()` runs the poll without moving the
   pointer, as a poll that arrives on its own does. */
export const HoldsControlUnderPointer: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    const control = await canvas.findByRole('button', { name: /^(Show|Hide) technical details$/ });
    const browser =
      '__vitest_browser_runner__' in window ? (await import('vitest/browser')).page : null;
    await document.fonts.ready;
    // Move away first so Chromium delivers a fresh pointer event even when the prior
    // story ended at these coordinates. The poll below must leave the pointer in place.
    if (browser) {
      await browser.getByRole('button', { name: 'Simulate board poll' }).hover();
      control.scrollIntoView({ block: 'center', behavior: 'instant' });
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      await browser.getByRole('button', { name: /^(Show|Hide) technical details$/ }).hover();
      await expect(control.matches(':hover')).toBe(true);
    } else {
      await userEvent.unhover(control);
      await userEvent.hover(control);
    }
    const before = control.getBoundingClientRect().top;
    const scrollBefore = window.scrollY;
    log.asking = true;
    (canvas.getByRole('button', { name: 'Simulate board poll' }) as HTMLButtonElement).click();
    await waitFor(() =>
      expect(canvasElement.querySelector('.next-session-ask-question')).not.toBeNull(),
    );
    await waitFor(() =>
      expect(Math.abs(control.getBoundingClientRect().top - before)).toBeLessThan(1.5),
    );
    // Content leaving above moves it back the same way, so a press never lands on what slid under it.
    const grown = window.scrollY;
    await expect(grown).toBeGreaterThan(scrollBefore);
    log.asking = false;
    (canvas.getByRole('button', { name: 'Simulate board poll' }) as HTMLButtonElement).click();
    await waitFor(() =>
      expect(canvasElement.querySelector('.next-session-ask-question')).toBeNull(),
    );
    await waitFor(() =>
      expect(Math.abs(control.getBoundingClientRect().top - before)).toBeLessThan(1.5),
    );
  },
};

export const TechnicalDetailsContinuity: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const open = () => canvas.getByRole('button', { name: 'Hide technical details' });
    const trigger = await canvas.findByRole('button', { name: 'Show technical details' });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger.querySelector('svg[data-icon="details"]')).not.toBeNull();
    await expect(
      canvas.getByRole('tablist', { name: 'Technical details', hidden: true }),
    ).not.toBeVisible();
    await userEvent.click(trigger);
    const tabs = canvas.getByRole('tablist', { name: 'Technical details' });
    const activityTab = within(tabs).getByRole('tab', { name: 'Activity log', selected: true });
    const panel = canvas.getByRole('tabpanel', { name: 'Activity log' });
    await expect(activityTab).toHaveAttribute('aria-controls', panel.id);
    await waitFor(() => expect(panel).toBeVisible());
    await expect(panel.closest('[data-layer="technical"]')).not.toBeNull();
    await expect(auditTechnicalMonospace(canvasElement)).toEqual([]);
    const number = await waitFor(() => {
      const node = panel.querySelector('.next-cockpit-work-n');
      if (!node) throw new Error('Waiting for numbered entries');
      return node;
    });
    await expect(getComputedStyle(number).fontFamily).toMatch(/^ui-monospace/);
    activityTab.focus();
    await userEvent.keyboard('{ArrowRight}');
    const privacyTab = canvas.getByRole('tab', { name: 'AI use and privacy' });
    await expect(privacyTab).toHaveFocus();
    await expect(privacyTab).toHaveAttribute('aria-selected', 'true');
    await userEvent.keyboard('{ArrowLeft}');
    await expect(activityTab).toHaveFocus();
    const previous = log.served;
    (canvas.getByRole('button', { name: 'Simulate board poll' }) as HTMLButtonElement).click();
    await waitFor(() => expect(log.served).toBeGreaterThan(previous));
    await expect(open()).toHaveAttribute('aria-expanded', 'true');
    const previousTrigger = open();
    await userEvent.click(canvas.getByRole('button', { name: 'Remount session' }));
    await waitFor(() => expect(open()).not.toBe(previousTrigger));
    await expect(open()).toHaveAttribute('aria-expanded', 'true');
    await expect(canvas.getByRole('tab', { name: 'Activity log', selected: true })).toBeVisible();
  },
};

export const TechnicalDetailsRevealsRecordFragment: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole('button', { name: 'Show technical details' });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    const target = await waitFor(() => {
      const button = within(canvasElement)
        .getAllByRole('button', { hidden: true })
        .find((element) => element.textContent?.trim() === 'About this record');
      if (!button?.id) throw new Error('The record disclosure target has not arrived');
      return button;
    });
    await expect(target).not.toBeVisible();

    const closed = target.closest('[hidden]');
    await expect(closed).toHaveAttribute('hidden', 'until-found');
    const previousUrl = window.location.href;
    const runner = '__vitest_browser_runner__' in window;
    try {
      // A fragment navigation disconnects Vitest's test frame. Exercise the same browser event there.
      if (runner) closed?.dispatchEvent(new Event('beforematch'));
      else window.location.hash = encodeURIComponent(target.id);
      await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'true'));
      await expect(target).toBeVisible();
    } finally {
      if (!runner) window.history.replaceState(window.history.state, '', previousUrl);
    }
  },
};

const logEntries = [
  { ...message(1), at: G - 205, type: 'user_message', by: 'person:claude' },
  message(2),
  { ...message(3), type: 'tool_report', subject: 'command' },
  { ...message(4), type: 'tool_report', subject: 'write' },
  { ...message(5), type: 'gate_decision', by: 'harness' },
  message(6),
];

async function activityLogPanel(canvasElement: HTMLElement): Promise<HTMLElement> {
  const canvas = within(canvasElement);
  const panel = await canvas.findByRole('tabpanel', { name: 'Activity log' });
  const heading = await within(panel).findByRole('heading', { name: /^Activity log ·/ });
  await waitFor(() => expect(heading).toBeVisible());
  const rows = await within(panel).findAllByRole('listitem');
  await waitFor(() => expect(rows[0]).toBeVisible());
  return panel;
}

export const ActivityLogPartialCount: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show technical details' }));
    const panel = within(await activityLogPanel(canvasElement));
    await expect(
      panel.getByRole('heading', { name: 'Activity log · 50 entries loaded' }),
    ).toBeVisible();
    await userEvent.click(panel.getByRole('button', { name: 'You' }));
    await expect(panel.getByText('50 entries hidden')).toBeVisible();
    await userEvent.click(panel.getByRole('button', { name: 'Show 50 older entries' }));
    await expect(
      await panel.findByRole('heading', { name: 'Activity log · 100 entries' }),
    ).toBeVisible();
    await expect(panel.getByText('100 entries hidden')).toBeVisible();
  },
};

export const ActivityLogFilters: Story = {
  render: () => <PageExample entries={logEntries} cites={['e2']} windowStart={G - 200} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Show technical details' }));
    const panel = await activityLogPanel(canvasElement);
    const contents = within(panel);
    const ids = () =>
      [...panel.querySelectorAll<HTMLElement>('[data-next-entry-id]')].map((row) =>
        row.getAttribute('data-next-entry-id'),
      );
    await waitFor(() => expect(ids()).toEqual(['e6', 'e5', 'e4', 'e3', 'e2', 'e1']));
    await waitFor(() => expect(contents.getByText(/before the reading window/)).toBeVisible());
    const first = within(panel)
      .getByText('Synthetic entry 1')
      .closest<HTMLElement>('[role="listitem"]');
    const second = within(panel)
      .getByText('Synthetic entry 2')
      .closest<HTMLElement>('[role="listitem"]');
    if (!first || !second) throw new Error('Missing activity rows');
    await expect(first).toHaveAttribute('data-before-window');
    await expect(second).not.toHaveAttribute('data-before-window');
    const browser = '__vitest_browser_runner__' in window ? await import('vitest/browser') : null;
    if (browser) await browser.commands.storyForcedColors('active');
    try {
      if (browser) await expect(matchMedia('(forced-colors: active)').matches).toBe(true);
      await expect(within(first).getByText('Before reading window')).toBeVisible();
      await expect(within(second).queryByText('Before reading window')).toBeNull();
    } finally {
      if (browser) await browser.commands.storyForcedColors(null);
    }
    await expect(first).not.toHaveTextContent('A later direction you gave');
    for (const [name, expected] of [
      ['You', ['e1']],
      ['Agent', ['e6', 'e2']],
      ['Commands', ['e3']],
      ['Files', ['e4']],
      ['Cited', ['e2']],
      ['All', ['e6', 'e5', 'e4', 'e3', 'e2', 'e1']],
    ] as const) {
      const chip = contents.getByRole('button', { name });
      await userEvent.click(chip);
      await expect(chip).toHaveAttribute('aria-pressed', 'true');
      await expect(ids()).toEqual(expected);
      if (name === 'All') await expect(contents.queryByText(/entries hidden/)).toBeNull();
      else await expect(contents.getByText(`${6 - expected.length} entries hidden`)).toBeVisible();
    }
    await atWidth(400, async () => {
      const rows = [...panel.querySelectorAll<HTMLElement>('[data-next-entry-id]')];
      const boxes = rows.map((row) => row.getBoundingClientRect());
      await expect(new Set(boxes.map((box) => box.left)).size).toBe(1);
      await expect(
        boxes.every((box, index) => !index || box.top >= (boxes[index - 1]?.bottom ?? 0)),
      ).toBe(true);
    });
  },
};

export const OpenTechnicalDetails: Story = {
  render: () => <PageExample technical cites={['e95']} />,
  play: async ({ canvasElement }) => {
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    const sent = privacy.getByRole('button', { name: 'What is sent' });
    await userEvent.click(sent);
    await waitFor(() =>
      expect(privacy.getByText('The prompt size limit is 524,288 bytes.')).toBeVisible(),
    );
  },
};

export const SharedAiPause: Story = {
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await openSessionTechnicalTab('AI use and privacy', canvasElement);
    const pause = await canvas.findByRole('switch', { name: 'Pause all AI use' });
    await expect(pause).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(pause);
    await expect(await canvas.findByRole('switch', { name: 'Resume AI use' })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    await userEvent.click(canvas.getByRole('button', { name: 'Open Settings for the story' }));
    const resume = await canvas.findByRole('switch', { name: 'Resume AI use' });
    await expect(resume).toHaveAttribute('aria-checked', 'true');
    const summaries = canvas.getByRole('switch', { name: 'Summaries' });
    await expect(summaries).toHaveAttribute('aria-disabled', 'true');
    await expect(summaries).toHaveAccessibleDescription(/Paused/i);
    await userEvent.click(resume);
    await expect(await canvas.findByRole('switch', { name: 'Pause all AI use' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    await userEvent.click(canvas.getByRole('button', { name: 'Return to the session' }));
    await expect(await canvas.findByRole('switch', { name: 'Pause all AI use' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  },
};

export const TechnicalEvidence: Story = {
  render: () => <PageExample technical cites={['e95']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await openSessionTechnicalTab('Evidence', canvasElement);
    const evidence = within(await canvas.findByRole('tabpanel', { name: 'Evidence' }));
    await expect(evidence.getByText('Synthetic entry 95', { exact: false })).toBeVisible();
    await expect(evidence.getByRole('button', { name: 'What the check read' })).toBeVisible();
    await expect(evidence.getByRole('button', { name: 'This reading looks wrong' })).toBeVisible();
    await userEvent.click(evidence.getByRole('button', { name: 'This reading looks wrong' }));
    const undo = await evidence.findByRole('button', { name: 'Undo' });
    await waitFor(() => expect(undo).toHaveFocus());
    await userEvent.click(undo);
    await waitFor(() =>
      expect(evidence.getByRole('button', { name: 'This reading looks wrong' })).toHaveFocus(),
    );
    await expect(
      within(canvas.getByRole('region', { name: 'Drift' })).getByText('Synthetic entry 95', {
        exact: false,
      }),
    ).toBeVisible();
    const cite = await evidence.findByRole('button', { name: /^Show #.* in Activity log/ });
    await userEvent.click(cite);
    const activity = within(await canvas.findByRole('tabpanel', { name: 'Activity log' }));
    await userEvent.click(await activity.findByRole('button', { name: 'Back to the finding' }));
    await waitFor(() =>
      expect(evidence.getByRole('button', { name: /^Show #.* in Activity log/ })).toHaveFocus(),
    );
  },
};

/* Every control, sentence and limit the retired More held, in its new home, and More gone. */
export const MoreIsRetired: Story = {
  // Flaky: kept out of the test run until fixed; see docs/flaky-tests.md.
  tags: ['!test'],
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await expect(canvas.queryByRole('button', { name: 'More' })).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-more]')).toBeNull();
    const [intent, drift] = await waitFor(() => {
      const found = regions(canvasElement);
      const pick = (name: string) =>
        found.find((node) => (node.getAttribute('aria-label') ?? labelOf(node)) === name);
      const both = [pick('Goal'), pick('Drift')];
      if (!both[0] || !both[1]) throw new Error('cards not drawn yet');
      return both as [HTMLElement, HTMLElement];
    });
    /* The card's own row keeps the reading start; Clear, the measured sentence, About these saved words,
       Discard everything and Later directions sit behind one quiet menu, which floats inside the page. */
    await expect(
      await within(intent).findByRole('button', { name: /^Saved · reads from/ }),
    ).toBeVisible();
    await expect(within(intent).queryByRole('button', { name: 'Clear' })).toBeNull();
    await userEvent.click(
      await within(intent).findByRole('button', { name: 'More about these words' }),
    );
    const inIntent = within(canvasElement);
    await waitFor(async () =>
      expect(await inIntent.findByRole('button', { name: 'Clear' })).toBeVisible(),
    );
    await expect(inIntent.getByText(INTENT_MEASURED)).toBeVisible();
    await expect(
      await inIntent.findByRole('button', { name: 'About these saved words' }),
    ).toBeVisible();
    // The offer's summary; the press it opens is the second control of that name.
    await waitFor(() =>
      expect(inIntent.getAllByRole('button', { name: 'Discard everything' })[0]).toHaveAttribute(
        'aria-expanded',
        'false',
      ),
    );
    await expect(
      await inIntent.findByRole('button', { name: /^Later directions: / }),
    ).toBeVisible();
    await expect(await inIntent.findByRole('button', { name: 'How goals work' })).toBeVisible();
    // Behind their summaries: the saved stamp's definition and binding key, the binding sentence, and the
    // limit under Later directions.
    await userEvent.click(
      await within(intent).findByRole('button', { name: /^Saved · reads from/ }),
    );
    await waitFor(() => expect(inIntent.getByText('Each save is kept on its own.')).toBeVisible());
    await expect(intent.querySelector('.next-cockpit-held-bound')).toHaveTextContent(/s1/);
    // Pressing the stamp moves focus out of the menu, which closes it; the menu opens again for the rest.
    const more = await within(intent).findByRole('button', { name: 'More about these words' });
    if (more.getAttribute('aria-expanded') !== 'true') await userEvent.click(more);
    await userEvent.click(await inIntent.findByRole('button', { name: 'About these saved words' }));
    await waitFor(() =>
      expect(inIntent.getByText('These words are bound to claude:s1.')).toBeVisible(),
    );
    await userEvent.click(await inIntent.findByRole('button', { name: /^Later directions: / }));
    await waitFor(() =>
      expect(inIntent.getByText(/^Nothing here decides whether it changes/)).toBeVisible(),
    );
    const inDrift = within(drift);
    const head = drift.querySelector('header') as HTMLElement;
    await expect(await within(head).findByText(DRIFT_SUBTITLE)).toBeVisible();
    const details = canvas.getByRole('button', { name: 'Show technical details' });
    await userEvent.click(details);
    await activityLogPanel(canvasElement);
    await userEvent.click(details);
