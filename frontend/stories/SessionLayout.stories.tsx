import { openSessionTechnicalTab } from './sessionTechnical';
import { SubagentsView } from '../src/sessions/DetailParts';
import { sessionSubagents } from '../src/sessions/detail';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { seeInContext } from './citation';
import { auditTechnicalMonospace } from './calm.audit';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { INTENT_MEASURED } from '../src/intent/sentences';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createShell } from '../src/shell/createShell';
import { GLOSSARY } from '../src/language/glossary';
import { WAITING_ANSWER_WHERE } from '../src/sessions/WaitingBlock';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { routeOf } from './drift.scenario';
import { settledLayout, settledRect } from './settled-layout';

/* The real session page over a scripted backend. */

const meta = { title: 'Sessions/Session page' } satisfies Meta;
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
const reading = (
  cites: readonly string[],
  readAt: number,
  windowStart: number,
  evidence?: 'model' | 'unasked',
) => ({
  revision_read: 1,
  revision_read_at: G - 200,
  window_start: windowStart,
  read_at: readAt,
  evidence_through: G - 10,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: evidence === 'unasked' ? 'unasked check at 01:46' : 'claude-sonnet-5-5 · read at 01:46',
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
      result: evidence === 'model' ? 'departure' : 'consistent with the evidence read',
      cites,
      detail: evidence ? 'The agent switched to an unrelated task.' : '',
      clause: 'Synthetic goal',
    },
    ...(evidence === 'model'
      ? {
          line_1: {
            result: 'consistent with the evidence read',
            cites: ['e96'],
            detail: '',
            clause: 'The tests complete',
          },
        }
      : {}),
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
  summaryWrites: number;
  failBoard: boolean;
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
  summaryWrites: 0,
  failBoard: false,
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
  evidence,
  readingUnavailable = false,
  annotations = true,
  settingsUnavailable = false,
  summariesUnavailable = false,
  sessionOverrides = {},
  recordState = 'ok',
  olderFails = false,
  contextFacts = [],
  reportsBlocks = true,
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
  readonly evidence?: 'model' | 'unasked';
  readonly readingUnavailable?: boolean;
  readonly annotations?: boolean;
  readonly settingsUnavailable?: boolean;
  readonly summariesUnavailable?: boolean;
  readonly entries?: readonly Record<string, unknown>[];
  readonly sessionOverrides?: Record<string, unknown>;
  readonly recordState?: 'ok' | 'unsupported' | 'unavailable';
  readonly olderFails?: boolean;
  readonly contextFacts?: readonly Record<string, unknown>[];
  readonly reportsBlocks?: boolean;
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
    log.summaryWrites = 0;
    log.failBoard = false;
    log.stallOlder = stallOlder;
    log.olderAsked = false;
    log.releaseOlder = null;
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    let generation = G;
    let paused = false;
    let summariesOff = false;
    let ciRead = 'on';
    let marked = false;
    const policy = () => ({
      consent: !paused && !readingUnavailable,
      off: paused,
      reason: readingUnavailable ? 'store-unavailable' : paused ? 'model-calls-paused' : '',
      providers: { claude: true },
      words: { claude: true },
      tool_output: { claude: ['api'] },
      used: readingUnavailable ? 0 : 1,
      limit: technical ? 100 : 10,
    });
    const sent = [
      'Sent: your goal, a bounded set of entries, and your messages and the agent’s messages.',
      'The agent’s newest final reply goes whole, up to 16,384 characters.',
      'Tool output includes a check’s command, result and last 180 characters of output, and paths of files written.',
      'To: reader.example, with credential shapes redacted, through your Claude Code sign-in.',
    ];
    const settings = {
      values: {
        analyze_prompt_bytes: 16384,
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
          if (log.failBoard) return new Response(null, { status: 503 });
          log.served += 1;
          return json({
            generated: generation++,
            annotate: annotations,
            annotate_cap: 240,
            annotate_goal_cap: 1000,
            reading_check: 'passed',
            ...(annotations ? { reading: policy() } : {}),
            ...(technical
              ? {
                  summaries: {
                    consent: !paused && !summariesOff && !summariesUnavailable,
                    off: summariesOff,
                    reason: summariesUnavailable
                      ? 'store-unavailable'
                      : paused
                        ? 'model-calls-paused'
                        : summariesOff
                          ? 'summaries-off'
                          : '',
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
                      destination: '',
                      words_destination: 'reader.example',
                      ci_read: ciRead,
                      capacity: {
                        kind: 'capacity-preview',
                        policy: 'analyze-context-v1',
                        maximum_prompt_bytes: 524288,
                        window_tokens: null,
                        window_source: 'unknown',
                        generation_reserve_tokens: 128000,
                        cli_reserve_tokens: 16384,
                        estimated_system_tokens: 0,
                        estimate_method: 'legacy-byte-cap',
                        fit_verified: false,
                        policy_verified: false,
                        configuration_reason: '',
                        reason: 'estimated',
                        can_lower_prompt_setting: true,
                      },
                      model: 'claude-sonnet-5-5',
                    }
                  : {}),
              },
            },
            harnesses: [
              {
                key: 'claude',
                label: 'Claude Code',
                reports_rate: true,
                reports_needs_input: reportsBlocks,
                discovered: true,
              },
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
                        tasks: [
                          { subject: 'running Bash', status: 'in_progress' },
                          { subject: 'Write the release notes', status: 'pending' },
                        ],
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
                      annotation_assessment: reading(cites, log.readAt, readingWindow, evidence),
                    }
                  : {}),
                ...sessionOverrides,
              },
            ],
          });
        }
        if (technical && url === '/api/settings')
          return settingsUnavailable ? new Response(null, { status: 503 }) : json(settings);
        if (technical && url === '/api/summary' && init?.method === 'POST') {
          log.summaryWrites += 1;
          const { consent } = JSON.parse(String(init.body));
          if (paused) return new Response(null, { status: 403 });
          summariesOff = consent === 'off';
          return json({ ok: true, summaries: { consent: !summariesOff, off: summariesOff } });
        }
        if (technical && url.startsWith('/api/reading-long-plan')) log.previews += 1;
        if (technical && url === '/api/annotate' && init?.method === 'POST') {
          const press = JSON.parse(String(init?.body));
          marked = press.not_accurate === true;
          return json({ outcome: 'stored', persisted: true });
        }
        if (technical && url === '/api/reading') {
          const { consent, ci_read } = JSON.parse(String(init?.body));
          if (ci_read) {
            ciRead = ci_read;
            return json({ ok: true, ci_read: ciRead });
          }
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
          return json({
            semantic: { facts: contextFacts },
            sources: {
              work: {
                tool_reports: [],
                ...(evidence
                  ? {
                      analysis_levels: [
                        {
                          harness: 'claude',
                          sid: 's1',
                          revision_read: 1,
                          read_at: log.readAt,
                          computed_at: log.readAt,
                          level: 'medium',
                          reasons: ['departure'],
                          cites,
                        },
                      ],
                    }
                  : {}),
              },
            },
          });
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
            state: older && olderFails ? 'unavailable' : recordState,
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

const ORDER = [
  'Asked you',
  'Goal',
  'Is it on track?',
  'Right now',
  "What's happened so far",
  'At a glance',
  'Project',
  'Show technical details',
];
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
    const title = await canvas.findByRole('heading', {
      level: 1,
      name: 'Synthetic layout session',
    });
    const header = title.closest('header') as HTMLElement;
    const progress = canvas.getAllByRole('button', { name: 'Check progress' })[0] as HTMLElement;
    await expect(header).toContainElement(progress);
    await expect(header).toHaveTextContent('State: Working');
    await expect(header.querySelector('[data-next-session-status] svg')).toBeNull();
    await expect(
      within(canvas.getByRole('region', { name: 'Right now' })).getByText(
        'Write the release notes',
      ),
    ).toBeVisible();
    const expected = [
      'Goal',
      'Is it on track?',
      'Right now',
      "What's happened so far",
      'At a glance',
      'Project',
    ];
    const wide = () =>
      waitFor(async () => {
        await expect(canvasElement.querySelector('.next-session-columns')).toHaveAttribute(
          'data-wide',
          'true',
        );
        const bounds = (name: string) =>
          canvas.getByRole('region', { name }).getBoundingClientRect();
        const head = header.getBoundingClientRect();
        const first = bounds('Goal');
        const right = bounds('Right now');
        await expect(Math.abs(head.left - first.left)).toBeLessThan(1);
        await expect(Math.abs(head.right - right.right)).toBeLessThan(1);
        await expect(first.top).toBeGreaterThanOrEqual(head.bottom);
        await expect(right.top).toBeGreaterThanOrEqual(head.bottom);
        await expect(right.left).toBeGreaterThan(first.right);
        for (const name of expected.slice(4))
          await expect(Math.abs(bounds(name).left - right.left)).toBeLessThan(1);
        for (const name of ['Is it on track?', "What's happened so far"])
          await expect(Math.abs(bounds(name).left - first.left)).toBeLessThan(1);
      });
    const narrow = () => inOrderTopToBottom(canvasElement, [...expected, 'Show technical details']);
    if ('__vitest_browser_runner__' in window) {
      const { page } = await import('vitest/browser');
      const before = { width: window.innerWidth, height: window.innerHeight };
      try {
        for (const width of [375, 1099]) {
          await page.viewport(width, 800);
          await expect(window.innerWidth).toBe(width);
          await narrow();
        }
        await page.viewport(1100, 800);
        await expect(window.innerWidth).toBe(1100);
        await wide();
      } finally {
        await page.viewport(before.width, before.height);
      }
    } else if (window.innerWidth >= 1100) {
      await wide();
    } else {
      await narrow();
    }
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
    await expect(
      within(canvasElement).getByRole('region', { name: 'Right now' }),
    ).toHaveTextContent(/Turn ended \d\d:\d\d · waiting for you/);
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
    const before = (await settledRect(control)).top;
    const scrollBefore = await settledLayout(() => window.scrollY);
    log.asking = true;
    (canvas.getByRole('button', { name: 'Simulate board poll' }) as HTMLButtonElement).click();
    await waitFor(() =>
      expect(canvasElement.querySelector('.next-session-ask-question')).not.toBeNull(),
    );
    await waitFor(async () =>
      expect(Math.abs((await settledRect(control)).top - before)).toBeLessThan(1.5),
    );
    // Content leaving above moves it back the same way, so a press never lands on what slid under it.
    const grown = await settledLayout(() => window.scrollY);
    await expect(grown).toBeGreaterThan(scrollBefore);
    log.asking = false;
    (canvas.getByRole('button', { name: 'Simulate board poll' }) as HTMLButtonElement).click();
    await waitFor(() =>
      expect(canvasElement.querySelector('.next-session-ask-question')).toBeNull(),
    );
    await waitFor(async () =>
      expect(Math.abs((await settledRect(control)).top - before)).toBeLessThan(1.5),
    );
  },
};

export const TechnicalDetailsContinuity: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const open = () => canvas.getByRole('button', { name: GLOSSARY.hideTechnicalDetails.plain });
    const trigger = await canvas.findByRole('button', {
      name: GLOSSARY.showTechnicalDetails.plain,
    });
    await expect(
      canvas.getAllByRole('button', { name: GLOSSARY.showTechnicalDetails.plain }),
    ).toHaveLength(1);
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger.querySelector('svg[data-icon="details"]')).not.toBeNull();
    await expect(
      canvas.getByRole('tablist', { name: 'Technical details', hidden: true }),
    ).not.toBeVisible();
    await userEvent.click(trigger);
    await expect(open()).toBe(trigger);
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

const forcedStatus = 'No status: a later command forces the exit status to 0';
const longPath = `frontend/src/sessions/${'nested-layout-'.repeat(10)}fixture.ts`;
const laterPrompt = 'Also check the layout at phone width.';
const activityColumns = [
  ['Check the session layout.', 'You Prompt'],
  ['The session layout is ready to check.', 'Agent said'],
  ['pnpm test', 'Agent command'],
  [longPath, 'Agent file written'],
  ['pnpm lint || true', 'Agent command'],
  [laterPrompt, 'You Prompt'],
] as const;
const columnEntries = [
  { ...logEntries[0], summary: activityColumns[0][0] },
  { ...message(2), summary: activityColumns[1][0] },
  {
    ...message(3),
    type: 'tool_report',
    subject: 'command',
    summary: activityColumns[2][0],
    result: 'passed',
    result_source: 'flag',
  },
  { ...message(4), type: 'tool_report', subject: 'write', summary: longPath },
  {
    ...message(5),
    type: 'tool_report',
    subject: 'command',
    summary: activityColumns[4][0],
    result: 'not-recorded',
    cannot_fail: true,
  },
  { ...message(6), type: 'user_message', by: 'person:claude', summary: laterPrompt },
];

async function openColumnExample(canvasElement: HTMLElement): Promise<HTMLElement> {
  const canvas = within(canvasElement);
  await userEvent.click(await canvas.findByRole('button', { name: 'Show technical details' }));
  return activityLogPanel(canvasElement);
}

export const ActivityLogEvenColumns: Story = {
  render: () => <PageExample entries={columnEntries} cites={['e2']} evidence="model" />,
  play: async ({ canvasElement }) => {
    await atWidth(1280, async () => {
      const log = within(await openColumnExample(canvasElement));
      const content = await Promise.all(
        activityColumns.map(async ([words, kind]) => ({ node: await log.findByText(words), kind })),
      );
      const assertAligned = async (panel: ReturnType<typeof within>) => {
        const lefts = await Promise.all(
          activityColumns.map(async ([words]) => {
            return (await settledRect(panel.getByText(words))).left;
          }),
        );
        await expect(
          Math.max(...lefts) - Math.min(...lefts),
          'Activity content shares a left edge',
        ).toBeLessThanOrEqual(0.5);
        return lefts;
      };

      const status = log.getByText(forcedStatus);
      await expect(status).toBeVisible();
      await expect(log.getByText('Exited 0')).toBeVisible();
      const closedLefts = await assertAligned(log);
      for (const { node, kind } of content) {
        const label = node.previousElementSibling;
        if (!label) throw new Error('Missing activity label');
        const [labelBox, contentBox] = await Promise.all([settledRect(label), settledRect(node)]);
        await expect(contentBox.left, 'Content sits beside its kind label').toBeGreaterThanOrEqual(
          labelBox.right,
        );
        await expect(contentBox.top).toBeLessThan(labelBox.bottom);
        await expect(label.textContent).toBe(kind);
        for (const part of [label, ...label.children]) {
          await expect(getComputedStyle(part).fontFamily).toMatch(/^Inter\b/i);
          await expect(getComputedStyle(part).fontWeight).toBe('400');
        }
      }
      const forced = status.closest<HTMLElement>('[role="listitem"]');
      if (!forced) throw new Error('Missing forced-status row');
      const source = within(forced).getByRole('button', { name: /^Source of entry/ });
      const [statusBox, sourceBox] = await Promise.all([settledRect(status), settledRect(source)]);
      const plain = log.getByText(activityColumns[3][0]);
      const plainRow = plain.closest<HTMLElement>('[role="listitem"]');
      const later = log.getByText('A later direction you gave');
      const laterRow = log.getByText(laterPrompt).closest<HTMLElement>('[role="listitem"]');
      if (!plainRow || !laterRow) throw new Error('Missing plain or later-direction row');
      await expect(laterRow).toContainElement(later);
      const cluster = later.closest('[data-activity-head-right]');
      if (!cluster) throw new Error('Missing later-direction details');
      const plainSource = within(plainRow).getByRole('button', { name: /^Source of entry/ });
      const [laterBox, plainBox, plainSourceBox] = await Promise.all([
        settledRect(cluster),
        settledRect(plain),
        settledRect(plainSource),
      ]);
      const center = (box: DOMRect) => box.top + box.height / 2;
      const trailingLayout = {
        statusSharesLineWithSource: Math.abs(center(statusBox) - center(sourceBox)) <= 3,
        laterDirectionStaysOnOneLine: laterBox.height <= 50,
        plainContentReachesSource: plainSourceBox.left - plainBox.right <= 20,
        detailsTextAlignsLeft: /^(left|start)$/.test(getComputedStyle(cluster).textAlign),
      };
      await userEvent.click(source);
      await expect(source).toHaveAttribute('aria-expanded', 'true');
      await expect(within(forced).getByText('transcript · exact')).toBeVisible();
      const openLefts = await assertAligned(log);
      for (const [index, left] of openLefts.entries()) {
        const closedLeft = closedLefts[index];
        if (closedLeft === undefined) throw new Error('Missing closed content position');
        await expect(
          Math.abs(left - closedLeft),
          'Opening Source preserves the content position',
        ).toBeLessThanOrEqual(0.5);
      }

      await openSessionTechnicalTab('Evidence', canvasElement);
      const citation = await within(canvasElement).findByRole('link', {
        name: 'Show #2 in Activity log for Goal: Synthetic goal',
      });
      await seeInContext(citation);
      const citedLog = within(await activityLogPanel(canvasElement));
      const citedRow = citedLog.getByText(activityColumns[1][0]).closest('[role="listitem"]');
      await waitFor(() => expect(citedRow).toHaveAttribute('data-next-cited'));
      await assertAligned(citedLog);

      await expect(trailingLayout).toEqual({
        statusSharesLineWithSource: true,
        laterDirectionStaysOnOneLine: true,
        plainContentReachesSource: true,
        detailsTextAlignsLeft: true,
      });
    });
  },
};

export const ActivityLogAtPhoneWidth: Story = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
  globals: { viewport: { value: 'mobile1', isRotated: false } },
  render: () => <PageExample entries={columnEntries} />,
  play: async ({ canvasElement }) => {
    await atWidth(320, async () => {
      const panel = await openColumnExample(canvasElement);
      const log = within(panel);
      const file = await log.findByText(longPath);
      const row = file.closest<HTMLElement>('[role="listitem"]');
      if (!row) throw new Error('Missing file row');
      const source = within(row).getByRole('button', { name: /^Source of entry/ });
      await userEvent.click(source);
      await expect(within(row).getByText('transcript · exact')).toBeVisible();
      await expect(log.getByText(forcedStatus)).toBeVisible();
      await expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth);
      await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
    });
  },
};

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
  render: () => <PageExample technical readingUnavailable />,
  play: async ({ canvasElement }) => {
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    await expect(privacy.getByText('reader.example · Claude Code')).toBeVisible();
    await expect(privacy.getByText('Daily check count unavailable.')).toBeVisible();
    await expect(privacy.queryByText('100 of 100 daily checks')).toBeNull();
    await userEvent.click(privacy.getByRole('button', { name: 'What is sent' }));
    await waitFor(() =>
      expect(
        privacy.getByText('Estimated prompt ceiling for this route: 524,288 bytes.'),
      ).toBeVisible(),
    );
    await userEvent.click(privacy.getByRole('button', { name: 'What is sent' }));
    const first = within(within(canvasElement).getByRole('region', { name: 'Is it on track?' }));
    await userEvent.click(first.getByRole('button', { name: 'What is sent' }));
    await waitFor(() =>
      expect(first.getByText('Estimated prompt ceiling for this route: 512 KB.')).toBeVisible(),
    );
    await expect(first.queryByText(/524,288 bytes/)).toBeNull();
    await userEvent.click(first.getByRole('button', { name: 'What is sent' }));
    const checks = await openSessionTechnicalTab('Check settings', canvasElement);
    await expect(await checks.findByText('16 KB of 2,048 KB allowed (16,384 bytes)')).toBeVisible();
  },
};

export const TechnicalPullRequestReadPointsToSettings: Story = {
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = within(await canvas.findByRole('region', { name: 'Is it on track?' }));
    await userEvent.click(first.getByRole('button', { name: 'What is sent' }));
    await waitFor(() =>
      expect(
        first.getByText(
          'Pull request checks are read from GitHub or GitLab with your gh or glab login when you press Check progress.',
        ),
      ).toBeVisible(),
    );
    await expect(
      first.queryByRole('button', { name: 'Turn off the pull request read' }),
    ).toBeNull();
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    await expect(
      privacy.getByRole('link', { name: 'Read pull request status in Settings' }),
    ).toHaveAttribute('href', '#n=settings');
  },
};

export const SharedAiPause: Story = {
  render: () => <PageExample technical annotations={false} settingsUnavailable />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const settings = canvas.getByRole('button', { name: 'Open Settings for the story' });
    const session = canvas.getByRole('button', { name: 'Return to the session' });
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    const firstPause = await privacy.findByRole('switch', { name: 'Pause all AI use' });
    await expect(firstPause).not.toBeChecked();
    await expect(firstPause).toHaveAccessibleDescription('Applies to every session.');

    for (const savedOn of [true, false]) {
      const pause = await canvas.findByRole('switch', { name: 'Pause all AI use' });
      await userEvent.click(pause);
      await expect(await canvas.findByRole('switch', { name: 'Resume AI use' })).toBeChecked();
      await userEvent.click(settings);
      await expect(await canvas.findByText(/could not be read/)).toBeVisible();
      const resume = await canvas.findByRole('switch', { name: 'Resume AI use' });
      await expect(resume).toBeChecked();
      const summaries = canvas.getByRole('switch', { name: 'Summaries' });
      await expect(summaries).not.toBeChecked();
      await expect(summaries).toHaveAttribute('aria-disabled', 'true');
      await expect(summaries).toHaveAccessibleDescription(/Paused/i);
      const writes = log.summaryWrites;
      await userEvent.click(summaries);
      await expect(log.summaryWrites).toBe(writes);
      await userEvent.click(resume);
      await expect(
        await canvas.findByRole('switch', { name: 'Pause all AI use' }),
      ).not.toBeChecked();
      await waitFor(() => expect(summaries.getAttribute('aria-checked')).toBe(String(savedOn)));
      if (savedOn) {
        await userEvent.click(summaries);
        await waitFor(() => expect(summaries).not.toBeChecked());
        await expect(log.summaryWrites).toBe(writes + 1);
      }
      await userEvent.click(session);
      await expect(
        await canvas.findByRole('switch', { name: 'Pause all AI use' }),
      ).not.toBeChecked();
    }
  },
};

export const FailedRefreshWithholdsBothPauseControls: Story = {
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
    await userEvent.click(await privacy.findByRole('switch', { name: 'Pause all AI use' }));
    const resume = await privacy.findByRole('switch', { name: 'Resume AI use' });
    await expect(resume).toBeChecked();
    await waitFor(() => expect(resume).not.toHaveAttribute('aria-busy'));
    await expect(await canvas.findByRole('button', { name: 'Resume AI use' })).toBeVisible();
    log.failBoard = true;
    await userEvent.click(canvas.getByRole('button', { name: 'Simulate board poll' }));
    await expect(
      await privacy.findByText('Compass could not refresh the AI pause setting.'),
    ).toBeVisible();
    await expect(privacy.queryByRole('switch', { name: 'Resume AI use' })).toBeNull();
    await expect(canvas.queryByRole('button', { name: 'Resume AI use' })).toBeNull();
  },
};

export const UnavailableSummaryGrant: Story = {
  render: () => <PageExample technical summariesUnavailable />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Open Settings for the story' }));
    await expect(await canvas.findByText('The Summaries setting is unavailable.')).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: 'Summaries' })).toBeNull();
    await expect(canvas.getByRole('switch', { name: 'Pause all AI use' })).toBeVisible();
  },
};

export const TechnicalTabsAtPhoneWidth: Story = {
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    await atWidth(400, async () => {
      const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
      const tabs = within(canvasElement).getAllByRole('tab');
      const labels = tabs.map((tab) => {
        const range = document.createRange();
        range.selectNodeContents(tab);
        return range.getBoundingClientRect();
      });
      const sameRow = labels.slice(1).flatMap((box, index) => {
        const previous = labels[index];
        return previous && Math.abs(previous.top - box.top) < 1 ? [box.left - previous.right] : [];
      });
      await expect(sameRow.length).toBeGreaterThan(0);
      await expect(Math.min(...sameRow)).toBeGreaterThan(0);

      const pause = privacy.getByText('Applies to every session.');
      const pullRequests = privacy.getByRole('link', {
        name: 'Read pull request status in Settings',
      });
      const explanation = privacy.getByText(/pull request checks are read from GitHub or GitLab/i);
      await expect((await settledRect(explanation)).top).toBeGreaterThanOrEqual(
        (await settledRect(pause)).bottom,
      );
      await expect((await settledRect(pullRequests)).top).toBeGreaterThanOrEqual(
        (await settledRect(explanation)).bottom,
      );
    });
  },
};

export const TechnicalEvidence: Story = {
  render: () => <PageExample technical evidence="model" cites={['e95']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(
      evidence.getByRole('heading', { name: 'Evidence for “Slightly off course”' }),
    ).toBeVisible();
    await expect(evidence.getByText('2 entries cited')).toBeVisible();
    await expect(evidence.getByText(/Synthetic entry 95/)).toBeVisible();
    await expect(evidence.getByText(/Synthetic entry 96/)).toBeVisible();
    await expect(evidence.getByRole('button', { name: 'What the check read' })).toBeVisible();

    const progress = within(canvas.getByRole('region', { name: 'Is it on track?' }));
    await expect(progress.queryByText(/Synthetic entry 95/)).toBeNull();
    await userEvent.click(progress.getByRole('button', { name: 'This reading looks wrong' }));
    const undo = await progress.findByRole('button', { name: 'Undo' });
    await waitFor(() => expect(undo).toHaveFocus());
    await expect(evidence.getByText(/^Marked inaccurate\./)).toBeVisible();
    await userEvent.click(undo);
    await waitFor(() =>
      expect(progress.getByRole('button', { name: 'This reading looks wrong' })).toHaveFocus(),
    );
    const cite = await evidence.findByRole('link', { name: /^Show #.* in Activity log for Goal/ });
    await seeInContext(cite);
    const activity = within(await canvas.findByRole('tabpanel', { name: 'Activity log' }));
    await userEvent.click(await activity.findByRole('button', { name: 'Back to the finding' }));
    await waitFor(() =>
      expect(
        canvas.getByRole('link', { name: /^Show #.* in Activity log for Goal/ }),
      ).toHaveFocus(),
    );
  },
};

export const UpdateMyGoalInsteadOpensTheEditor: Story = {
  render: () => <PageExample technical evidence="model" cites={['e95']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const goal = within(await canvas.findByRole('region', { name: 'Goal' }));
    const progress = within(await canvas.findByRole('region', { name: 'Is it on track?' }));
    await expect(goal.queryByRole('textbox', { name: 'Goal' })).toBeNull();
    await userEvent.click(await progress.findByRole('button', { name: 'Update my goal instead' }));
    const field = goal.getByRole('textbox', { name: 'Goal' });
    await expect(field).toHaveFocus();
    await expect(field).toHaveValue('Synthetic goal');
  },
};

export const TechnicalEvidenceUnasked: Story = {
  render: () => <PageExample technical evidence="unasked" cites={['e95']} />,
  play: async ({ canvasElement }) => {
    const evidence = await openSessionTechnicalTab('Evidence', canvasElement);
    await expect(evidence.getByText(/^Unasked check at \d{2}:\d{2}/)).toBeVisible();
  },
};

async function technicalTabInventory(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  const privacy = await openSessionTechnicalTab('AI use and privacy', canvasElement);
  const monitor = privacy.getByRole('switch', { name: 'Live monitor' });
  await expect(monitor).toBeVisible();
  await expect(monitor).toHaveAccessibleDescription(
    /Checks progress about once a minute while you watch/,
  );
  await expect(privacy.getByText('Live monitor · Haiku')).toBeVisible();
  await expect(privacy.getByText(/Applies to every session/)).toBeVisible();
  await expect(privacy.getByText('99 of 100 daily checks')).toBeVisible();
  await expect(
    privacy.getByRole('link', { name: 'Read pull request status in Settings' }),
  ).toBeVisible();
  await expect(privacy.getByRole('switch', { name: 'Pause all AI use' })).toBeVisible();
  await userEvent.click(privacy.getByRole('button', { name: 'What is sent' }));
  await waitFor(() =>
    expect(
      privacy.getByText('Estimated prompt ceiling for this route: 524,288 bytes.'),
    ).toBeVisible(),
  );
  await expect(privacy.queryByRole('dialog')).toBeNull();
  const disclosure = privacy.getByText('Estimated prompt ceiling for this route: 524,288 bytes.');
  await expect(disclosure.closest('[data-slot="accordion-content"]')).not.toBeNull();
  await expect(disclosure.closest('[data-slot="popover-content"]')).toBeNull();

  const checks = await openSessionTechnicalTab('Check settings', canvasElement);
  await expect(await checks.findByText(/16 KB of 2,048 KB/)).toBeVisible();
  for (const label of [
    'Prompt size limit',
    'Messages, tests and builds kept',
    'Tests, builds and files listed',
    'Transcript scanned for tests and builds',
  ]) {
    await expect(checks.getByText(label)).toBeVisible();
  }
  await expect(checks.getByRole('link', { name: 'Settings' })).toHaveAttribute(
    'href',
    '#n=settings',
  );
  await expect(checks.getByRole('button', { name: 'Unfinished long checks' })).toBeVisible();
  await userEvent.click(checks.getByRole('button', { name: 'Long check for very long sessions' }));
  await waitFor(() =>
    expect(checks.getByRole('button', { name: 'Refresh long preview' })).toBeVisible(),
  );
  await userEvent.click(canvas.getByRole('button', { name: 'Remount session' }));
  const restored = within(await canvas.findByRole('tabpanel', { name: 'Check settings' }));
  await expect(log.previews).toBe(1);
  await expect(
    restored.getByRole('button', { name: 'Long check for very long sessions' }),
  ).toHaveAttribute('aria-expanded', 'true');
  await expect(restored.getByRole('button', { name: 'Refresh long preview' })).toBeVisible();

  const reports = await openSessionTechnicalTab('Reports', canvasElement);
  await expect(reports.getByRole('heading', { name: /How it landed/i })).toBeVisible();
  await expect(reports.getByRole('button', { name: /^command-shape reports/i })).toBeVisible();
  await expect(reports.getByText('Accepted by macOS.')).toBeVisible();

  const activity = await openSessionTechnicalTab('Activity log', canvasElement);
  await expect(activity.queryByText(/Command-shape reports/i)).toBeNull();
  await expect(activity.queryByText('Accepted by macOS.')).toBeNull();
}

export const TechnicalTabInventory: Story = {
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    await technicalTabInventory(canvasElement);
  },
};

/* Goal and progress explain themselves in place. TechnicalTabInventory covers the controls in the tabs. */
export const MoreIsRetired: Story = {
  render: () => <PageExample technical />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await expect(canvas.queryByRole('button', { name: 'More' })).toBeNull();
    await expect(canvasElement.querySelector('[data-next-session-more]')).toBeNull();
    const intent = canvas.getByRole('region', { name: 'Goal' });
    const inIntent = within(intent);
    await expect(inIntent.queryByRole('button', { name: 'More about these words' })).toBeNull();
    await expect(inIntent.queryByRole('button', { name: 'Clear' })).toBeNull();
    const how = inIntent.getByRole('button', { name: 'How goals work' });
    await expect(inIntent.getByRole('button', { name: 'Edit goal' })).toBeVisible();
    await expect(inIntent.queryByRole('button', { name: 'Save intent' })).toBeNull();
    await userEvent.click(how);
    await waitFor(async () => {
      await expect(inIntent.getByText(INTENT_MEASURED)).toBeVisible();
      await expect(inIntent.getByText(/^Reads from /)).toBeVisible();
      await expect(inIntent.getByText('These words are bound to claude:s1.')).toBeVisible();
      await expect(inIntent.getByText(/Each save is kept on its own/)).toBeVisible();
    });
    await userEvent.click(how);
    await userEvent.click(inIntent.getByRole('button', { name: 'Edit goal' }));
    await expect(inIntent.getByRole('button', { name: 'Clear' })).toBeVisible();
    await expect(inIntent.getByRole('button', { name: 'Discard everything' })).toBeVisible();
    await userEvent.click(inIntent.getByRole('button', { name: /^Later directions: / }));
    await waitFor(() =>
      expect(inIntent.getByText(/^Nothing here decides whether it changes/)).toBeVisible(),
    );
    await expect(
      intent.querySelector('[data-slot="popover-content"] [data-slot="popover-content"]'),
    ).toBeNull();
    const inDrift = within(canvas.getByRole('region', { name: 'Is it on track?' }));
    await expect(inDrift.queryByRole('switch', { name: 'Live monitor' })).toBeNull();
    await expect(inDrift.queryByRole('button', { name: 'Drift settings' })).toBeNull();
    await expect(inDrift.queryByText(/^Delegated work:/)).toBeNull();
    await expect(
      canvas.getAllByRole('button', { name: 'Check progress' })[0] as HTMLElement,
    ).toBeVisible();
    await userEvent.click(inDrift.getByRole('button', { name: 'What is sent' }));
    await waitFor(() =>
      expect(inDrift.getByText('Estimated prompt ceiling for this route: 512 KB.')).toBeVisible(),
    );

    await openSessionTechnicalTab('Activity log', canvasElement);
  },
};

export const MoreIsRetiredForAnEndedSession: Story = {
  render: () => <PageExample ended />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'How goals work' }));
    await waitFor(() =>
      expect(
        canvas.getByText(/^This session has ended. Compass keeps goals you save now/),
      ).toBeVisible(),
    );
  },
};

function spyScroll() {
  const calls: (ScrollIntoViewOptions | boolean | undefined)[] = [];
  const original = Element.prototype.scrollIntoView;
  const media = window.matchMedia;
  Element.prototype.scrollIntoView = function scroll(options) {
    calls.push(options);
    original.call(this, options);
  };
  window.matchMedia = (query: string) =>
    ({ ...media.call(window, query), matches: query.includes('reduce') }) as MediaQueryList;
  return {
    calls,
    restore: () => {
      Element.prototype.scrollIntoView = original;
      window.matchMedia = media;
    },
  };
}

/* The Goal cites an entry on the older record page. The press opens Activity log, reads that page, and lands
   on the entry with its tint; Escape goes back to the press, and neither move animates under reduced motion. */
export const CitationLoadsAnOlderEntry: Story = {
  render: () => <PageExample cites={['e5']} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const scroll = spyScroll();
    try {
      const jump = () =>
        canvas.getByRole('button', {
          name: 'Load the cited entries in Activity log for Goal: Synthetic goal',
        });
      await waitFor(() =>
        expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(50),
      );
      await expect(canvasElement.querySelector('[data-next-entry-id="e5"]')).toBeNull();
      const trigger = canvas.getByRole('button', { name: /^(Show|Hide) technical details$/ });
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      await openSessionTechnicalTab('Activity log', canvasElement);
      const tab = canvas.getByRole('tab', { name: 'Activity log', selected: true });
      const panel = canvas.getByRole('tabpanel', { name: 'Activity log' });
      await expect(tab).toHaveAttribute('aria-controls', panel.id);
      await userEvent.click(within(panel).getByRole('button', { name: 'Cited' }));
      await openSessionTechnicalTab('Evidence', canvasElement);
      await expect(jump()).toBeVisible();
      await userEvent.click(jump());
      await expect(trigger).toHaveAttribute('aria-expanded', 'true');
      await expect(tab).toHaveAttribute('aria-selected', 'true');
      await waitFor(() =>
        expect(within(panel).getByRole('button', { name: 'Cited', pressed: true })).toBeVisible(),
      );
      const row = await waitFor(() => {
        const found = canvasElement.querySelector<HTMLElement>('[data-next-entry-id="e5"]');
        if (!found) throw new Error('the older page has not arrived');
        return found;
      });
      await waitFor(() => expect(document.activeElement).toBe(row));
      await expect(row).toHaveAttribute('data-next-cited');
      await expect(getComputedStyle(row).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
      // Wait for the row to land inside the viewport as the accordion settles.
      await waitFor(() => {
        const box = row.getBoundingClientRect();
        expect(box.bottom).toBeGreaterThan(0);
        expect(box.top).toBeLessThan(window.innerHeight);
      });
      await expect(scroll.calls.at(-1)).toEqual({ behavior: 'instant', block: 'center' });
      /* Once the entry is held, the finding names it by its number instead of offering to load it, and the
         way back lands on that number. */
      const cited = () =>
        canvas.getByRole('link', {
          name: /^Show #\d+(\.\d+)? in Activity log for Goal: Synthetic goal$/,
        });
      await userEvent.keyboard('{Escape}');
      await waitFor(() => expect(cited()).toHaveFocus());
      await expect(scroll.calls.at(-1)).toEqual({ behavior: 'instant', block: 'center' });
      // A citation also lands from a filter that would otherwise hide its entry.
      await openSessionTechnicalTab('Activity log', canvasElement);
      await userEvent.click(within(panel).getByRole('button', { name: 'You' }));
      await openSessionTechnicalTab('Evidence', canvasElement);
      await seeInContext(cited());
      const reopened = await waitFor(() => {
        const found = panel.querySelector('[data-next-entry-id="e5"]');
        if (!found) throw new Error('Waiting for the cited entry');
        return found;
      });
      await waitFor(() => expect(document.activeElement).toBe(reopened));
      await userEvent.click(
        within(reopened as HTMLElement).getByRole('button', { name: 'Back to the finding' }),
      );
      await waitFor(() => expect(cited()).toHaveFocus());
    } finally {
      scroll.restore();
    }
  },
};

/* The Goal cites an entry no record page returns. The press reads to the record's start, then says so where it
   would have landed, and focus goes there rather than staying on a control whose answer is elsewhere. */
export const CitationThatCannotLoadSaysSo: Story = {
  render: () => <PageExample cites={['ghost']} />,
  play: async ({ canvasElement }) => {
    await openSessionTechnicalTab('Evidence', canvasElement);
    const canvas = within(canvasElement);
    const jump = () =>
      canvas.getByRole('button', {
        name: 'Load the cited entries in Activity log for Goal: Synthetic goal',
      });
    await waitFor(() => expect(jump()).toBeVisible());
    await userEvent.click(jump());
    const note = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-jump-missing]');
      if (!found) throw new Error('the read has not finished');
      return found;
    });
    await expect(note).toHaveTextContent(
      'An entry this finding cites could not be loaded: the record read for this session does not list it.',
    );
    await expect(note).toHaveAttribute('role', 'status');
    await waitFor(() => expect(document.activeElement).toBe(note));
    await expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100);
    await userEvent.click(within(note).getByRole('button', { name: 'Back to the finding' }));
    await waitFor(() => expect(jump()).toHaveFocus());
    // Escape on the way back, too, returns to the finding rather than leaving the session page.
    await userEvent.click(jump());
    // The press takes the old sentence down and draws its own.
    const again = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-jump-missing]');
      if (!found || document.activeElement !== found) throw new Error('not landed yet');
      return found;
    });
    within(again).getByRole('button', { name: 'Back to the finding' }).focus();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(jump()).toHaveFocus());
    await expect(
      canvas.getByRole('heading', { level: 1, name: 'Synthetic layout session' }),
    ).toBeVisible();
  },
};

/* A retained reading: the intent was saved again with a later window, and the Goal cites `e5`, from before
   that window and on the older record page. The first page already reaches past the window, so Show more says
   nothing about older entries, yet the press still reads the older page and lands on the entry. */
export const RetainedReadingCitesBeforeTheWindow: Story = {
  render: () => <PageExample cites={['e5']} windowStart={G - 30} revised />,
  play: async ({ canvasElement }) => {
    await openSessionTechnicalTab('Evidence', canvasElement);
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]').length).toBeGreaterThan(0),
    );
    const jump = await canvas.findByRole('button', {
      name: 'Load the cited entries in Activity log for Goal: Synthetic goal',
    });
    await expect(canvasElement.querySelector('[data-next-unloaded]')).toBeNull();
    await expect(canvasElement.querySelector('[data-next-entry-id="e5"]')).toBeNull();
    await userEvent.click(jump);
    const row = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-entry-id="e5"]');
      if (!found) throw new Error('the older page has not arrived');
      return found;
    });
    await waitFor(() => expect(document.activeElement).toBe(row));
    await expect(row).toHaveAttribute('data-next-cited');
    const swatch = document.createElement('span');
    swatch.style.backgroundColor = 'color-mix(in srgb, var(--accent) 13%, transparent)';
    swatch.style.color = 'var(--accent)';
    row.append(swatch);
    const tint = getComputedStyle(swatch).backgroundColor;
    const edge = getComputedStyle(swatch).color;
    swatch.remove();
    await expect(getComputedStyle(row).backgroundColor).toBe(tint);
    await expect(getComputedStyle(row).borderLeftColor).toBe(edge);
    await expect(within(row).getByText('Before reading window')).toBeVisible();
    const ordinary = canvasElement.querySelector<HTMLElement>(
      '[data-next-entry-id]:not([data-next-cited])',
    );
    const citedContent = row.querySelector('.next-cockpit-work-summary');
    const ordinaryContent = ordinary?.querySelector('.next-cockpit-work-summary');
    if (!ordinary || !citedContent || !ordinaryContent) throw new Error('Missing activity rows');

    const browser = '__vitest_browser_runner__' in window ? await import('vitest/browser') : null;
    if (browser) await browser.commands.storyForcedColors('active');
    try {
      if (browser) await expect(matchMedia('(forced-colors: active)').matches).toBe(true);
      await expect(getComputedStyle(row).borderLeftWidth).toBe('3px');
      await expect(getComputedStyle(ordinary).borderLeftWidth).toBe('0px');
      const spread = await settledLayout(() =>
        Math.abs(
          citedContent.getBoundingClientRect().left - ordinaryContent.getBoundingClientRect().left,
        ),
      );
      await expect(spread).toBeLessThanOrEqual(0.5);
    } finally {
      if (browser) await browser.commands.storyForcedColors(null);
    }
  },
};

/* The Goal cites `e5`, on the older page and from before the window the reading itself read. The press loads it,
   but the reading's own rules set it aside, so no row is marked: the sentence says so and takes focus. */
export const CitationSetAsideByTheReadingSaysSo: Story = {
  render: () => <PageExample cites={['e5']} readingWindow={G - 60} />,
  play: async ({ canvasElement }) => {
    await openSessionTechnicalTab('Evidence', canvasElement);
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole('button', {
        name: 'Load the cited entries in Activity log for Goal: Synthetic goal',
      }),
    );
    const note = await waitFor(() => {
      const found = canvasElement.querySelector<HTMLElement>('[data-next-jump-missing]');
      if (!found) throw new Error('the read has not finished');
      return found;
    });
    await expect(note).toHaveTextContent(
      /^The entries this finding cites are loaded, but none is marked/,
    );
    await waitFor(() => expect(document.activeElement).toBe(note));
    await expect(canvasElement.querySelector('[data-next-entry-id="e5"]')).not.toBeNull();
    await expect(canvasElement.querySelector('[data-next-cited]')).toBeNull();
  },
};

async function pollWithNewReading(canvasElement: HTMLElement) {
  const before = log.served;
  log.readAt = G - 5;
  await userEvent.click(within(canvasElement).getByRole('button', { name: 'Simulate board poll' }));
  await waitFor(() => expect(log.served).toBeGreaterThan(before));
}

/* The press's older page is slow, and a new reading arrives while it is read. When the page finally answers,
   the press it served belongs to a reading that is gone, so no "could not be loaded" sentence appears. */
export const SlowReadEndsAfterANewReading: Story = {
  render: () => <PageExample cites={['ghost']} stallOlder />,
  play: async ({ canvasElement }) => {
    await openSessionTechnicalTab('Evidence', canvasElement);
    const canvas = within(canvasElement);
    const jump = await canvas.findByRole('button', {
      name: 'Load the cited entries in Activity log for Goal: Synthetic goal',
    });
    await userEvent.click(jump);
    await waitFor(() => expect(log.releaseOlder).not.toBeNull());
    await pollWithNewReading(canvasElement);
    log.releaseOlder?.();
    await waitFor(() =>
      expect(canvasElement.querySelectorAll('[data-next-entry-id]')).toHaveLength(100),
    );
    // Long enough for the ended read's settle to have drawn the sentence, were it going to.
    await new Promise((resolve) => setTimeout(resolve, 150));
    await expect(canvasElement.querySelector('[data-next-jump-missing]')).toBeNull();
  },
};

/* The sentence stands, then a new reading arrives: the sentence and the press it answered go with the old
   reading, and the control it kept drawn goes too, since the record has been read to its start. */
export const NoteLeavesWithItsReading: Story = {
  render: () => <PageExample cites={['ghost']} />,
  play: async ({ canvasElement }) => {
    await openSessionTechnicalTab('Evidence', canvasElement);
    const canvas = within(canvasElement);
    const name = 'Load the cited entries in Activity log for Goal: Synthetic goal';
    await userEvent.click(await canvas.findByRole('button', { name }));
    await waitFor(() =>
      expect(canvasElement.querySelector('[data-next-jump-missing]')).not.toBeNull(),
    );
    await pollWithNewReading(canvasElement);
    await waitFor(() => expect(canvasElement.querySelector('[data-next-jump-missing]')).toBeNull());
    await expect(canvas.queryByRole('button', { name })).toBeNull();
  },
};

/* A question arrives while the page is open: it leads the page, one press sends the exact request and option,
   and a second press while that one is pending sends nothing. */
export const QuestionLeadsAndAnswersOnce: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole('heading', { level: 1, name: 'Synthetic layout session' });
    await waitFor(() =>
      expect(named(canvasElement)).toEqual(expect.arrayContaining(ORDER.slice(1))),
    );
    log.asking = true;
    await userEvent.click(canvas.getByRole('button', { name: 'Simulate board poll' }));
    await atWidth(1099, () => inOrderTopToBottom(canvasElement, ORDER));
    const asked = regions(canvasElement)[0] as HTMLElement;
    await expect(asked).toHaveTextContent('Run the synthetic migration now?');
    const yes = within(asked).getByRole('button', { name: 'Yes, run it' });
    await userEvent.click(yes);
    await waitFor(() => expect(log.answers).toHaveLength(1));
    await expect(JSON.parse(log.answers[0] ?? '{}')).toEqual({ id: 'q1', index: 0 });
    await waitFor(() => expect(yes).toHaveAttribute('aria-busy', 'true'));
    await userEvent.click(yes);
    await userEvent.click(within(asked).getByRole('button', { name: 'Not yet' }));
    await expect(log.answers).toHaveLength(1);
    log.release?.();
    await waitFor(() => expect(named(canvasElement)[0]).toBe('Goal'));
    await expect(log.answers).toHaveLength(1);
  },
};

/* A question Compass shortened says so under its options, with the length the session sent and how many options
   were never shown; the cut text still ends in "…", and the longest labels wrap inside the card at phone width. */
export const ShortenedQuestion: Story = {
  render: () => <PageExample asking ask={SHORTENED_ASK} />,
  play: async ({ canvasElement }) => {
    const asked = await within(canvasElement).findByRole('region', { name: 'Asked you' });
    for (const width of [1280, 400]) {
      await atWidth(width, async () => {
        const question = asked.querySelector('.next-session-ask-question') as HTMLElement;
        await expect(question.textContent).toHaveLength(2_000);
        await expect(question.textContent?.endsWith('…')).toBe(true);
        const notes = [...asked.querySelectorAll<HTMLElement>('[data-next-session-ask-cut]')];
        await expect(notes.map((note) => note.textContent)).toEqual([
          'Shortened by Compass: the session sent 2,500 characters.',
          '2 more options were not shown.',
        ]);
        for (const note of notes) await expect(note).toBeVisible();
        const buttons = within(asked).getAllByRole('button');
        await expect(buttons).toHaveLength(3);
        const card = asked.getBoundingClientRect();
        for (const button of buttons)
          await expect(button.getBoundingClientRect().right).toBeLessThanOrEqual(card.right + 1);
        // Below the options, so the reader meets the choice first and the note before leaving it.
        const options = asked.querySelector('.next-session-answer-options') as HTMLElement;
        await expect(notes[0]?.getBoundingClientRect().top).toBeGreaterThanOrEqual(
          options.getBoundingClientRect().bottom,
        );
        await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
      });
    }
  },
};

/* A question inside every cap carries no note. */
export const UnshortenedQuestionHasNoNote: Story = {
  render: () => <PageExample asking />,
  play: async ({ canvasElement }) => {
    const asked = await within(canvasElement).findByRole('region', { name: 'Asked you' });
    await expect(asked).toHaveTextContent('Run the synthetic migration now?');
    await expect(asked.querySelector('[data-next-session-ask-cut]')).toBeNull();
  },
};

/* A session waiting on you is marked beside its title, not down its page (owner, 2026-10-29): the page is one
   unpadded column, and an inset stripe on it ran its full height and over the title's first letter. */
export const WaitingEdgeStaysBesideTheTitle: Story = {
  render: () => <PageExample gate />,
  play: async ({ canvasElement }) => {
    const heading = await within(canvasElement).findByRole('heading', {
      level: 1,
      name: 'Synthetic layout session',
    });
    const page = canvasElement.querySelector<HTMLElement>('.next-session-detail--blocked');
    await expect(page).not.toBeNull();
    await expect(getComputedStyle(page as HTMLElement).boxShadow).toBe('none');
    const header = heading.closest('header') as HTMLElement;
    await expect(getComputedStyle(header).borderLeftWidth).toBe('3px');
    await expect(heading.getBoundingClientRect().left).toBeGreaterThan(
      header.getBoundingClientRect().left + 10,
    );
    const columns = canvasElement.querySelector('.next-session-columns') as HTMLElement;
    await expect(columns.getBoundingClientRect().top).toBeGreaterThanOrEqual(
      header.getBoundingClientRect().bottom,
    );
  },
};

/* A harness's own gate has no request Compass can show or answer, so it is said on its own: waiting, for how
   long, what the harness said, and where it is answered. The command back in stays on Attention. */
export const HarnessGateSaysWhereToAnswer: Story = {
  render: () => <PageExample gate />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const block = await canvas.findByRole('region', { name: 'Waiting on you' });
    await expect(block).toHaveTextContent('Waiting on you · 15m');
    await expect(block).toHaveTextContent('Permission prompt: Bash');
    await expect(block).toHaveTextContent(WAITING_ANSWER_WHERE);
    const link = within(block).getByRole('link', { name: 'Needs you' });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', '#n=attention');
    await expect(within(block).queryByRole('button', { name: /Copy/ })).toBeNull();
    await expect(regions(canvasElement)[0]).toBe(block);
    // It stands apart from the header above it and the card below it, as the cards stand apart from each other.
    const box = block.getBoundingClientRect();
    const above = (block.previousElementSibling as HTMLElement).getBoundingClientRect();
    const below = (block.nextElementSibling as HTMLElement).getBoundingClientRect();
    await expect(box.top - above.bottom).toBeGreaterThanOrEqual(16);
    await expect(below.top - box.bottom).toBeGreaterThanOrEqual(16);
    await expect(canvas.queryByRole('region', { name: 'Asked you' })).toBeNull();
    await waitFor(() => expect(document.title).toMatch(/^● Needs you · /));
    const icon = document.head.querySelector('link[data-next-favicon]');
    await expect(decodeURIComponent(icon?.getAttribute('href') ?? '')).toContain('fill="#92400e"');
  },
};

/* Attention carries a command back in only where the session publishes a token its CLI takes, so the block
   names Attention for it only then. */
export const HarnessGateWithNoWayBackNamesNoCommand: Story = {
  render: () => <PageExample gate resumable={false} />,
  play: async ({ canvasElement }) => {
    const block = await within(canvasElement).findByRole('region', { name: 'Waiting on you' });
    await expect(block).toHaveTextContent(WAITING_ANSWER_WHERE);
    await expect(within(block).queryByRole('link', { name: 'Needs you' })).toBeNull();
    await expect(block).not.toHaveTextContent('The command back into it');
  },
};

export const FullActivityLinksToGoalHistory: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole('button', { name: /^(Show|Hide) technical details$/ }),
    );
    const summary = await canvas.findByText('What it keeps');
    const history = summary.closest<HTMLElement>('.next-cockpit-departures-kept');
    if (!history) throw new Error('The history disclosure is missing');
    const link = within(history).getByRole('link', { name: 'Goal history' });
    await waitFor(() => expect(link).toBeVisible());
    await expect(link).toHaveAttribute('href', '#n=intent');
    await userEvent.click(summary);
    const description = within(history).getByText(
      'Goal history keeps what you saved and what was raised against it after the session leaves the board.',
    );
    await waitFor(() => expect(description).toBeVisible());
  },
};

/* An exact request keeps its own Asked-you block; the waiting block is for the gate Compass cannot answer. */
export const ExactRequestKeepsItsOwnBlock: Story = {
  render: () => <PageExample asking />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const asked = await canvas.findByRole('region', { name: 'Asked you' });
    await expect(asked.querySelector('[data-next-session-wait-note]')).toBeNull();
    await expect(canvas.queryByRole('region', { name: 'Waiting on you' })).toBeNull();
    await waitFor(() => expect(document.title).toMatch(/^● Needs you · /));
  },
};

export const HarnessGateWithExactRequest: Story = {
  render: () => <PageExample asking gate />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const asked = within(await canvas.findByRole('region', { name: 'Asked you' }));
    await expect(asked.getByText(String(ASK.question))).toBeVisible();
    await expect(asked.getByText('Permission prompt: Bash', { exact: true })).toBeVisible();
    await expect(asked.getByText('Agent reports:', { exact: true })).toBeVisible();
    await expect(asked.queryByText('Harness reports:', { exact: true })).toBeNull();
    await expect(canvas.queryByRole('region', { name: 'Waiting on you' })).toBeNull();
  },
};

/* A working session carries no waiting sign anywhere: no edge, no block, and the resting tab. */
export const WorkingSessionCarriesNoWaitingSign: Story = {
  render: () => <PageExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = await canvas.findByRole('heading', {
      level: 1,
      name: 'Synthetic layout session',
    });
    await expect(getComputedStyle(heading.closest('header') as HTMLElement).borderLeftWidth).toBe(
      '0px',
    );
    await expect(canvas.queryByRole('region', { name: 'Waiting on you' })).toBeNull();
    await waitFor(() => expect(document.title).not.toMatch(/^● Needs you · /));
    const icon = document.head.querySelector('link[data-next-favicon]');
    await expect(decodeURIComponent(icon?.getAttribute('href') ?? '')).toContain(
      'stroke="#2f7d5b"',
    );
  },
};

export const IdleQuestionPrecedesTurnEnd: Story = {
  render: () => <PageExample idle asking />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('heading', {
      level: 1,
      name: 'Synthetic layout session',
    });
    const activity = canvasElement.querySelector(
      '[data-next-session-command="activity"]',
    ) as HTMLElement;
    await expect(activity).toHaveTextContent(String(ASK['question']));
    await expect(activity).not.toHaveTextContent('Turn ended');
    const metadata = canvasElement.querySelector('.next-session-detail-meta') as HTMLElement;
    await expect(metadata).not.toHaveTextContent(/Turn ended|Run finished/);
  },
};

export const EndedWithAnOpenQuestion: Story = {
  render: () => <PageExample idle ended asking />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const answer = await canvas.findByRole('button', { name: 'Yes, run it' });
    const status = canvasElement.querySelector('.next-session-state');
    await expect(status).toBeVisible();
    await expect(status).toHaveTextContent('State: Ended');
    await expect(answer).toBeVisible();
    await expect(answer).toBeEnabled();
  },
};

export const HelperActivity: Story = {
  render: () => {
    const helpers = sessionSubagents(
      [
        { name: 'Review results', active: true, started_at: G - 60 },
        { name: 'Read documentation', active: false },
        { name: 'Check types' },
      ],
      0,
      G,
    );
    if (!helpers) throw new Error('Expected the synthetic helpers');
    return <SubagentsView subagents={helpers} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const helpers = canvas.getByRole('list', { name: 'Helpers (3)' });
    /* Each helper has a named tile. No harness records a helper's finish, so one that is not running is State
       not known with its words kept beside it (owner, 2026-11-24). */
    for (const [name, tile, word] of [
      ['Review results', 'Working', ''],
      ['Read documentation', 'State not known', 'Not running'],
      ['Check types', 'State not known', 'Activity not published'],
    ] as const) {
      const helper = canvas.getByText(name).closest('[data-next-session-subagent]') as HTMLElement;
      await expect(within(helper).getByRole('img', { name: tile })).toBeVisible();
      if (word) await expect(helper).toHaveTextContent(word);
    }
    await expect(within(helpers).queryByRole('img', { name: 'Ended' })).toBeNull();
  },
};

export const EndedHasNoCurrentNextStep: Story = {
  render: () => <PageExample ended />,
  play: async ({ canvasElement }) => {
    const now = within(await within(canvasElement).findByRole('region', { name: 'Right now' }));
    await expect(now.getByText('Session reported its own end', { exact: true })).toBeVisible();
    await expect(now.queryByText('Next step', { exact: true })).toBeNull();
    await expect(now.queryByText('Write the release notes', { exact: true })).toBeNull();
    await expect(now.queryByText('No reported block', { exact: true })).toBeNull();
  },
};

export const IdentifierOnlyTitle: Story = {
  render: () => <PageExample sessionOverrides={{ title: 's1', annotation_goal: '' }} />,
  play: async ({ canvasElement }) => {
    const title = await within(canvasElement).findByRole('heading', {
      level: 1,
      name: 'Title not published',
    });
    await expect(title).not.toHaveAttribute('data-authored');
  },
};

export const UnnamedHelper: Story = {
  render: () => <PageExample sessionOverrides={{ subagents: [{ active: true }] }} />,
  play: async ({ canvasElement }) => {
    const now = within(await within(canvasElement).findByRole('region', { name: 'Right now' }));
    await expect(now.getByRole('heading', { name: 'Helpers (1)' })).toBeVisible();
    await expect(now.getByText('Unnamed helper', { exact: true })).not.toHaveAttribute(
      'data-authored',
    );
    await expect(now.getByRole('img', { name: 'Working' })).toBeVisible();
    await expect(now.queryByText('subagent', { exact: true })).toBeNull();
  },
};

function figuresStory(
  props: Parameters<typeof PageExample>[0],
  words: string,
  absent: string,
): Story {
  return {
    render: () => <PageExample {...props} />,
    play: async ({ canvasElement }) => {
      const region = await within(canvasElement).findByRole('region', { name: 'At a glance' });
      await waitFor(() => expect(region.textContent).toBe(`At a glance${words}`));
      await expect(within(region).queryByText(absent, { exact: true })).toBeNull();
    },
  };
}

export const FiguresPublished = figuresStory(
  { entries: [message(1)] },
  'Recorded entries1',
  'At least 1',
);
export const FiguresMeasuredZero = figuresStory(
  { entries: [] },
  'Recorded entries0',
  'No figures published for this session.',
);
export const FiguresPartial = figuresStory({}, 'Recorded entriesAt least 50', '50');
export const FiguresUnsupported = figuresStory(
  { recordState: 'unsupported' },
  'No figures published for this session.',
  'Recorded entries',
);
export const FiguresUnavailable = figuresStory(
  { recordState: 'unavailable' },
  'No figures published for this session.',
  'Recorded entries',
);

export const FailedOlderPageKeepsFiguresPartial: Story = {
  render: () => <PageExample olderFails />,
  play: async ({ canvasElement }) => {
    const region = await within(canvasElement).findByRole('region', { name: 'At a glance' });
    await expect(await within(region).findByText('At least 50', { exact: true })).toBeVisible();
    await openSessionTechnicalTab('Activity log', canvasElement);
    await userEvent.click(
      await within(canvasElement).findByRole('button', { name: /^Show \d+ older entries$/ }),
    );
    await expect(
      await within(canvasElement).findByText('Could not read older entries', { exact: true }),
    ).toBeVisible();
    await expect(region.textContent).toBe('At a glanceRecorded entriesAt least 50');
    await expect(within(region).queryByText('50', { exact: true })).toBeNull();
  },
};

export const FiguresUnavailableWithRetainedEntry = figuresStory(
  { recordState: 'unavailable', contextFacts: [message(1)] },
  'Recorded entriesAt least 1',
  '1',
);

export const PublishedTokenFigures = figuresStory(
  {
    recordState: 'unsupported',
    sessionOverrides: { session_output_tokens: 0, turn_output_tokens: 1234 },
  },
  'Session output tokens0Turn output tokens1,234',
  'Recorded entries',
);

const noActivity = { tasks: undefined, state_detail: undefined };
function nowStory(
  props: Parameters<typeof PageExample>[0],
  words: string,
  forbidden: readonly string[],
): Story {
  return {
    render: () => <PageExample {...props} />,
    play: async ({ canvasElement }) => {
      const region = await within(canvasElement).findByRole('region', { name: 'Right now' });
      await expect(region.textContent).toBe(`Right now${words}`);
      for (const word of forbidden)
        await expect(within(region).queryByText(word, { exact: true })).toBeNull();
    },
  };
}

export const RightNowWithoutActivity = nowStory(
  { sessionOverrides: noActivity },
  'Activity not publishedNext stepNo pending step publishedBlocked?No reported block',
  [
    'No state published',
    'Waiting on you',
    'Block state could not be read',
    'Write the release notes',
  ],
);

export const RightNowWithoutState = nowStory(
  { sessionOverrides: { ...noActivity, state: undefined } },
  'No state publishedNext stepNo pending step publishedBlocked?No reported block',
  [
    'Activity not published',
    'Waiting on you',
    'Block state could not be read',
    'Write the release notes',
  ],
);

export const RightNowWithoutBlockReporting = nowStory(
  { sessionOverrides: noActivity, reportsBlocks: false },
  'Activity not publishedNext stepNo pending step publishedBlocked?This agent does not report blocks',
  [
    'Harness does not report blocks',
    'No reported block',
    'Waiting on you',
    'Block state could not be read',
  ],
);

export const RightNowWithUnreadableBlock = nowStory(
  { sessionOverrides: { ...noActivity, source_gaps: ['block state'] } },
  'Activity not publishedSome activity could not be read: block state.Next stepNo pending step publishedBlocked?Block state could not be read',
  ['No reported block', 'Waiting on you', 'This agent does not report blocks'],
);

export const RightNowWithReportedBlock = nowStory(
  { gate: true },
  'Permission prompt: BashNext stepNo pending step publishedBlocked?Waiting on youPermission prompt: Bash',
  ['No reported block', 'Block state could not be read', 'Write the release notes'],
);
