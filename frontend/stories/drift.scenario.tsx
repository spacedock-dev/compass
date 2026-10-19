import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createShell } from '../src/shell/createShell';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* One whole page over a scripted backend, for the stories that hold the Intent and drift card by stage, by
   harness and by route. The real provider, router and Drift card run; only the network is a double, and a
   path nobody scripted answers `{}`, so a request nobody meant to make cannot reach a model or a session.
   Not a story file, so Storybook lists nothing from it and the route-reason guard can import its table. */

export type Harness = 'claude' | 'pi' | 'codex' | 'antigravity';

/* A route as the server publishes it (`reading_route.Route`), so a story edits only what it is about. */
export interface RouteFields {
  readonly provider: string;
  readonly label: string;
  readonly reason: string;
  readonly note: string;
  readonly fallback: boolean;
}

export function routeOf(harness: string, fields: RouteFields): Record<string, unknown> {
  const reads = fields.provider !== '';
  const claude = fields.provider === 'claude';
  const parts = reads
    ? [
        fields.note,
        `This sends the session to ${fields.label}.`,
        'Your saved words.',
        ...(harness === 'claude' ? ['The agent messages and tool output are included.'] : []),
      ]
    : [];
  return {
    harness,
    provider: fields.provider,
    label: fields.label,
    vendor: '',
    model: reads ? 'm' : '',
    reason: fields.reason,
    note: fields.note,
    disclosure: parts.join(' '),
    disclosure_parts: parts,
    fallback: fields.fallback,
    destination: claude ? 'api' : '',
    tool_output: claude ? 'Tool output goes to the api.' : '',
    words_destination: reads ? 'api' : '',
  };
}

/* Every harness has a reader on a healthy machine: Claude Code reads its own, Codex reads its own, and Pi and
   Antigravity have no producer of their own, so Codex reads them. */
function healthyRoute(harness: Harness): Record<string, unknown> {
  if (harness === 'claude') {
    return routeOf(harness, {
      provider: 'claude',
      label: 'Claude Code',
      reason: 'own-harness',
      note: "This session's own harness reads it.",
      fallback: false,
    });
  }
  return harness === 'codex'
    ? routeOf(harness, {
        provider: 'codex',
        label: 'Codex',
        reason: 'own-harness',
        note: "This session's own harness reads it.",
        fallback: false,
      })
    : routeOf(harness, {
        provider: 'codex',
        label: 'Codex',
        reason: 'no-own-producer',
        note: 'This harness has no reading producer of its own, so Codex reads this session.',
        fallback: false,
      });
}

export interface ReadingScenario {
  readonly replies: readonly (Record<string, unknown> | null)[];
  readonly posts: Record<string, unknown>[];
  finish: (() => Promise<void>) | null;
}

export const readingScenario = (
  replies: readonly (Record<string, unknown> | null)[],
): ReadingScenario => ({ replies, posts: [], finish: null });

export interface Scenario {
  readonly reading?: ReadingScenario;

  readonly harness?: Harness;
  /** What the board publishes for this session, over the saved intent below. */
  readonly session?: Record<string, unknown>;
  /** A session with no saved words: the first prompt is drafted into the goal box and nothing is stored. */
  readonly unsaved?: boolean;
  readonly payload?: Record<string, unknown>;
  readonly facts?: readonly unknown[];
  readonly work?: Record<string, unknown>;
  /** The route for this harness, where a story is about a machine that is not the healthy one. */
  readonly route?: Record<string, unknown>;
  /** Whether `POST /api/annotate` keeps a Not accurate mark, as the store does, so the next board carries it. */
  readonly keepsMarks?: boolean;
}

export const fact = (
  id: string,
  at: number,
  extra: Record<string, unknown> = {},
  harness: string = 'claude',
) => ({
  fact_id: id,
  type: 'tool_report',
  by: 'agent',
  summary: `Entry ${id}`,
  at,
  source_session: { harness, sid: 's1' },
  evidence: { source: 'transcript', confidence: 'exact' },
  ...extra,
});

/* Two different commands, so a later pass of one does not stand over the failure of the other. */
export const failedCheck = (id: string, at: number, harness = 'claude') =>
  fact(
    id,
    at,
    { subject: 'check', result: 'failed', result_source: 'failed flag', summary: 'pytest -q' },
    harness,
  );
export const passedCheck = (id: string, at: number, harness = 'claude') =>
  fact(
    id,
    at,
    { subject: 'check', result: 'passed', result_source: 'passed flag', summary: 'ruff check .' },
    harness,
  );
export const written = (id: string, at: number, path: string, harness = 'claude') =>
  fact(id, at, { subject: 'write', summary: path }, harness);

/* The saved words every stage but the first reads against. */
const SAVED = {
  annotation_goal: 'Ship the queue',
  annotation_line_1: 'Tests pass',
  annotation_revision: 3,
  annotation_revision_count: 1,
  annotation_at: 990,
  annotation_goal_saved_at: 990,
  annotation_window_start: 100,
};

/* What the server publishes on every row while annotations are on (`reading.press_eligibility`). Each story
   mounts a running session, which every harness may be read while it runs, so the press is open and a story
   that asserts Analyze is asserting what the server would let the reader press. A withheld press is the
   board's own refusal and is not what these stories are about. */
const ELIGIBLE = { ok: true, reason: null, until: null, sentence: null };

const POLICY = {
  consent: true,
  off: false,
  reason: '',
  providers: { claude: true, codex: true },
  words: { claude: true, codex: true },
  tool_output: { claude: ['api'] },
  used: 1,
  limit: 10,
};

function DriftScenario({ scenario }: { readonly scenario: Scenario }) {
  const [shell] = useState(() => {
    const harness = scenario.harness ?? 'claude';
    const clock = createFakeClock();
    const history = fakeRouterEnvironment(`#n=session:demo:${harness}:s1`);
    let generation = 1000;
    let marked: boolean | null = null;
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    let job: Record<string, unknown> | null = null;
    let reading = scenario.payload?.['reading'] ?? POLICY;
    if (scenario.reading) scenario.reading.posts.length = 0;
    const shell = createShell({
      env: createFakeEnvironment({ clock }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        if (url.startsWith('/api/reading') && scenario.reading) {
          const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
          const index = scenario.reading.posts.length;
          scenario.reading.posts.push(body);
          if (body['consent'] === 'off') {
            reading = { consent: false, off: true, reason: 'model-calls-paused' };
            return json({ ok: true, reading });
          }
          reading = POLICY;
          if (body['consent'] === 'on') return json({ ok: true, reading });
          const notice = scenario.reading.replies[index];
          job = { ...JOB, id: `notice-${index}`, ...(notice ? { notice } : {}) };
          return new Response(JSON.stringify({ ok: true, job, ...(notice ? { notice } : {}) }), {
            status: 202,
          });
        }
        if (scenario.keepsMarks && url.startsWith('/api/annotate')) {
          const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
          if (typeof body['not_accurate'] === 'boolean') {
            marked = body['not_accurate'];
            return json({ ok: true, outcome: 'stored', persisted: true });
          }
        }
        if (url.startsWith('/api/data'))
          return json({
            generated: generation++,
            annotate: true,
            annotate_cap: 240,
            reading_check: 'passed',
            reading_routes: { [harness]: scenario.route ?? healthyRoute(harness) },
            ...(scenario.payload ?? {}),
            reading,
            ...(job ? { reading_jobs: { [`${harness}:s1`]: job } } : {}),
            sessions: [
              {
                harness,
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic session',
                state: 'working',
                first_prompt: 'Ship the queue worker',
                first_prompt_at: 100,
                reading_eligibility: ELIGIBLE,
                ...(scenario.unsaved ? {} : SAVED),
                ...(scenario.session ?? {}),
                ...(marked === null ? {} : { annotation_not_accurate: marked }),
              },
            ],
          });
        if (url.startsWith('/api/project-context'))
          return json({
            semantic: { facts: scenario.facts ?? [] },
            sources: { work: { tool_reports: [], ...(scenario.work ?? {}) } },
          });
        if (url.startsWith('/api/session-record'))
          return json({ state: 'ok', entries: [], next: null, reached_start: true });
        if (url.startsWith('/api/annotations'))
          return json({ annotations: [], intent_revision: 'r1' });
        return json({});
      },
    });
    if (scenario.reading)
      scenario.reading.finish = async () => {
        job = null;
        await shell.runtime.refresh({ manual: true });
      };
    return shell;
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

export { DriftScenario };

/* A stored reading of `Ship the queue`: the goal departs on a failed check, the one outcome line is
   consistent on a passing one. Read at 1000 against revision 3. */
export const DEPARTURE_READING = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
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
      result: 'departure',
      cites: ['c1'],
      detail: 'It stopped running the tests.',
      clause: 'Ship the queue',
    },
    line_1: {
      result: 'consistent with the evidence read',
      cites: ['c2'],
      detail: '',
      clause: 'Tests pass',
    },
  },
};

export const STORED_READING = {
  annotation_assessment: DEPARTURE_READING,
  annotation_reading_count: 1,
};

/* A running reading as `reading.published_jobs` publishes it: the three phases in the order they happen, worded
   by `reading.PHASE_TEXT` with the receiver's label filled in. `drift.reasons.test.ts` reads both from the
   producer, so a reworded or renamed phase fails there before a story passes over a step that is gone. */
export const JOB_STEPS = [
  { phase: 'preparing', text: 'Preparing what is sent' },
  { phase: 'waiting', text: 'Waiting for Claude Code' },
  { phase: 'checking', text: 'Checking the reply' },
];
export const JOB = {
  id: 'j1',
  phase: 'waiting',
  phase_at: 995,
  started_at: 990,
  provider: 'claude',
  cancelling: false,
  steps: JOB_STEPS,
};

/* The analysis level the server derives from the stored reading and publishes beside it
   (`http_api._analysis_levels`): it is the level the card draws over a result. */
export const analysisRow = (harness: Harness, level = 'high') => ({
  harness,
  sid: 's1',
  revision_read: 3,
  read_at: 1000,
  computed_at: 1000,
  level,
  reasons: ['failed-check'],
  cites: ['c1'],
});
