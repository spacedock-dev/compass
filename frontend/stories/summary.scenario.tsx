import { useEffect, useState } from 'react';
import { App } from '../src/App';
import type { Shell } from '../src/shell/context';
import { createShell } from '../src/shell/createShell';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { routeOf } from './drift.scenario';
import { G, claudeOutline, recordFor } from './outline.scenario';

/* One session page over a scripted backend for the summary stories: the board with its `summaries` grant
   block, a saved intent and, where a story asks, a stored reading whose departures cite the record; the focused
   context carrying `sources.outline` and `sources.summary` in the shapes `summary_store.focused` and
   `summary_jobs` publish; the record pages; and the summary routes, answered by the story. Every request is
   recorded so a story can assert what was, and was not, sent. Not a story file. */

export const MADE_AT = G - 120;
export const STAMP = 'claude:claude-sonnet-5-5:0123456789abcdef0123456789abcdef';

export const grant = (over: Record<string, unknown> = {}) => ({
  consent: true,
  off: false,
  used: 4,
  limit: 200,
  retry_at: null,
  reason: '',
  notice_due: false,
  provider: 'claude',
  destination: 'Anthropic',
  disclosure:
    "Summaries send redacted session text in windows of at most 16 KiB: your words, the agent's replies, masked check titles and file-write display paths. Sent through your Claude Code to Anthropic.",
  notices: {},
  ...over,
});

export const NOTICE = {
  kind: 'summary',
  provider: 'claude',
  destination: 'Anthropic',
  content: 1,
  tool_output: '',
  at: G - 30,
};

export const job = (over: Record<string, unknown> = {}) => ({
  id: 'job-1',
  state: 'running',
  part: 0,
  parts: 3,
  reason: '',
  finished_parts: [],
  attempts: 0,
  started_at: G - 30,
  notice: null,
  ...over,
});

const COVERAGE = {
  complete: true,
  starts_at: null,
  start_offset: 0,
  end_offset: 4096,
  unread: [],
  notes: [],
  agent_replies: 'read',
  checks_and_files: 'read',
};

export const bullet = (text: unknown, kind: string, cites: readonly string[]) => ({
  text,
  kind,
  cites: [...cites],
  kind_overridden: false,
});

/* The record's two parts, each a phase: what the person asked, what the agent said, and the check that failed. */
export const FIRST_PHASE = {
  title: 'Adding retry to the webhook handler',
  bullets: [
    bullet('Asked for retry with backoff on the webhook handler.', 'asked', ['p1']),
    bullet('Said the retry wrapper is being added.', 'said', ['a1']),
    bullet('pytest tests/test_webhook.py reported failed, as the tool reported.', 'failed', ['c1']),
  ],
};
export const SECOND_PHASE = {
  title: 'Keeping the diff small',
  bullets: [
    bullet('Asked to keep the diff small and leave the tests alone.', 'asked', ['p2']),
    bullet('Reverting the test edit.', 'said', ['a2']),
  ],
};

export const block = (first: string, last: string, entries: number, phases: unknown[]) => ({
  first,
  last,
  entries,
  fingerprint: `${first}${last}`.padEnd(32, '0'),
  phases,
});
export const gap = (first: string, last: string, entries: number, reason: string) => ({
  first,
  last,
  entries,
  fingerprint: `${first}${last}`.padEnd(32, '0'),
  gap: true,
  reason,
  see: 'outline',
});

export const LEDE =
  'The person asked for retry with backoff on the webhook handler. The agent worked on a retry wrapper, then reverted a test edit after being asked to leave the tests alone.';

/* `summary_store.focused` for a saved summary. */
export function storedSummary(over: Record<string, unknown> = {}) {
  return {
    state: 'ok',
    reason: null,
    harness: 'claude',
    starts_at: null,
    lede: { text: LEDE, cites: ['p1', 'p2'] },
    lede_reason: null,
    blocks: [block('p1', 'c2', 4, [FIRST_PHASE]), block('p2', 'a2', 2, [SECOND_PHASE])],
    spend: { calls: 3, bytes_sent: 9000, bytes_back: 1200, seconds: 18, retries: 0 },
    coverage: COVERAGE,
    change: null,
    affected_blocks: [],
    exists: true,
    made_at: MADE_AT,
    model_stamp: STAMP,
    out_of_date: {
      kind: 'unchanged',
      reason: null,
      affected_blocks: [],
      new_entries: 0,
      appendable: false,
      action: null,
    },
    job: null,
    ...over,
  };
}

/* The outline's record, then the work after the reader's intent was saved: a failed check, which the stored
   reading's departure cites, and one more reply of the agent's. */
export function summaryRecord() {
  const after = (id: string, type: string, ordinal: number, at: number, extra = {}) => ({
    fact_id: id,
    at,
    type,
    by: 'agent',
    source_session: { harness: 'claude', sid: 's1' },
    evidence: { source: 'transcript', confidence: 'exact' },
    ordinal,
    ...extra,
  });
  return [
    ...recordFor('claude'),
    after('c3', 'tool_report', 4, G - 240, {
      summary: 'pytest tests/test_webhook.py',
      ordinal_sub: 1,
      result: 'failed',
      result_source: 'failed flag',
      source_kind: 'check_run',
      subject: 'check',
    }),
    after('a3', 'agent_message', 5, G - 230, { summary: 'The test file is restored.' }),
  ];
}

export const ABSENT = { state: 'absent', exists: false, job: null };

/* A stored reading of `Ship the webhook retry`, read after every entry, so it is current: the goal departs on
   the entries `cites` names. */
export function departureReading(cites: readonly string[], over: Record<string, unknown> = {}) {
  return {
    annotation_assessment: {
      revision_read: 3,
      revision_read_at: G - 280,
      window_start: G - 900,
      read_at: G,
      evidence_through: G,
      goal_source: 'typed',
      scope: 'last-turn',
      scope_text: 'Read up to its last turn.',
      stamp: 'claude-sonnet-5-5 · read at 09:38',
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
          cites: [...cites],
          detail: 'The tests were edited, which the goal ruled out.',
          clause: 'Ship the webhook retry',
        },
        line_1: {
          result: 'consistent with the evidence read',
          cites: ['c2'],
          detail: '',
          clause: 'Lint stays clean',
        },
      },
    },
    annotation_reading_count: 1,
    ...over,
  };
}

const SAVED = {
  annotation_goal: 'Ship the webhook retry',
  annotation_line_1: 'Lint stays clean',
  annotation_revision: 3,
  annotation_revision_count: 1,
  annotation_at: G - 280,
  annotation_goal_saved_at: G - 280,
  annotation_window_start: G - 900,
};

export interface Reply {
  readonly status: number;
  readonly body: Record<string, unknown>;
}

export interface SummaryScript {
  /** The board's `summaries` block, or null for a server that publishes none. */
  grant: Record<string, unknown> | null;
  /** The focused `sources.summary`. */
  summary: Record<string, unknown> | null;
  /** The row's own published fields, laid over the session. */
  session: Record<string, unknown>;
  /** Every POST to a summary route, in order. */
  posts: { path: string; body: Record<string, unknown> }[];
  /** How a summary POST is answered; the default admits a start with a running job. Status 0 loses the reply. */
  answer: (path: string, body: Record<string, unknown>) => Reply;
  /** How many boards the page has asked for. */
  boards: number;
  /** The focused `sources.outline`. */
  outline: Record<string, unknown>;
  shell: Shell | null;
}

export const script: SummaryScript = {
  grant: null,
  summary: null,
  session: {},
  posts: [],
  answer: () => ({ status: 202, body: { ok: true, job: job() } }),
  boards: 0,
  outline: {},
  shell: null,
};

export const defaultAnswer = (path: string, body: Record<string, unknown>): Reply => {
  if (path === '/api/summary' && 'consent' in body) {
    const on = body['consent'] === 'on';
    script.grant = grant(on ? {} : { consent: false, off: true, reason: 'summaries-off' });
    return { status: 200, body: { ok: true, summaries: script.grant } };
  }
  if (path === '/api/summary/cancel') return { status: 202, body: { ok: true, cancelling: true } };
  if (path === '/api/summary/delete') return { status: 200, body: { outcome: 'deleted' } };
  return { status: 202, body: { ok: true, job: job() } };
};

/* Asks the page for the next board, as a poll would, without touching focus. */
export async function poll(): Promise<void> {
  await script.shell?.runtime.refresh();
}

export function SummaryPage({
  grant: published = grant(),
  summary = ABSENT,
  ended = true,
  paged = false,
  session = {},
  answer = defaultAnswer,
  outline = claudeOutline({}, true),
}: {
  readonly grant?: Record<string, unknown> | null;
  readonly summary?: Record<string, unknown> | null;
  readonly ended?: boolean;
  readonly paged?: boolean;
  readonly session?: Record<string, unknown>;
  readonly answer?: SummaryScript['answer'];
  readonly outline?: Record<string, unknown>;
}) {
  const [shell] = useState(() => {
    script.grant = published;
    script.summary = summary;
    script.session = session;
    script.posts = [];
    script.answer = answer;
    script.boards = 0;
    script.outline = outline;
    const history = fakeRouterEnvironment('#n=session:demo:claude:s1');
    let generation = G;
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    const record = summaryRecord();
    const shell = createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url, init) => {
        const path = url.split('?')[0] ?? url;
        if ((init?.method ?? 'GET').toUpperCase() === 'POST' && path.startsWith('/api/summary')) {
          const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
          script.posts.push({ path, body });
          const reply = script.answer(path, body);
          if (reply.status === 0) throw new TypeError('The reply was lost.');
          return json(reply.body, reply.status);
        }
        if (url.startsWith('/api/data')) {
          script.boards += 1;
          return json({
            generated: generation++,
            annotate: true,
            annotate_cap: 240,
            reading_check: 'passed',
            reading: { consent: true, off: false, reason: '', used: 1, limit: 100 },
            reading_routes: {
              claude: routeOf('claude', {
                provider: 'claude',
                label: 'Claude Code',
                reason: 'own-harness',
                note: "This session's own harness reads it.",
                fallback: false,
              }),
            },
            ...(script.grant ? { summaries: script.grant } : {}),
            harnesses: [{ key: 'claude', label: 'Claude Code' }],
            sessions: [
              {
                harness: 'claude',
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic summary session',
                state: ended ? 'idle' : 'working',
                started_at: G - 3600,
                first_prompt: 'Add retry with backoff to the webhook handler.',
                first_prompt_at: G - 600,
                reading_eligibility: { ok: true, reason: null, until: null, sentence: null },
                ...(ended ? { ended_at: G - 60 } : {}),
                ...SAVED,
                ...script.session,
              },
            ],
          });
        }
        if (url.startsWith('/api/project-context')) {
          if (!url.includes('session='))
            return json({ semantic: { facts: [] }, sources: { work: {} } });
          return json({
            semantic: { facts: [] },
            sources: {
              work: { tool_reports: [] },
              outline: script.outline,
              ...(script.summary ? { summary: script.summary } : {}),
            },
          });
        }
        if (url.startsWith('/api/annotations'))
          return json({ annotations: [], intent_revision: 'r1' });
        if (url.startsWith('/api/session-record')) {
          const older = url.includes('before=');
          const page = !paged
            ? record
            : record.filter((row) => (older ? row.ordinal < 3 : row.ordinal >= 3));
          return json({
            state: 'ok',
            session: { harness: 'claude', sid: 's1' },
            entries: [...page].reverse(),
            next: paged && !older ? 'older' : null,
            reached_start: !paged || older,
            bound: null,
            scanned_bytes: 4096,
            kinds: ['user_message', 'agent_message', 'tool_report'],
          });
        }
        return json({});
      },
    });
    script.shell = shell;
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
