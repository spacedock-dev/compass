import { useEffect, useState } from 'react';
import { App } from '../src/App';
import { createShell } from '../src/shell/createShell';
import { createRouter } from '../src/router/router';
import { fakeRouterEnvironment } from '../src/router/testing';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';

/* One session page over a scripted backend for the What the session has done stories: the board, a focused
   context carrying `sources.outline` as `session_outline.build` shapes it, and one record page whose fact ids
   the outline's spans name. Not a story file, so Storybook lists nothing from it. */

export const G = 1900000000;

const fact = (
  harness: string,
  id: string,
  type: string,
  ordinal: number,
  at: number,
  summary: string,
  extra: Record<string, unknown> = {},
) => ({
  fact_id: id,
  at,
  type,
  by: type === 'user_message' ? 'user' : 'agent',
  source_session: { harness, sid: 's1' },
  summary,
  evidence: { source: 'transcript', confidence: 'exact' },
  ordinal,
  ...extra,
});

/* The record the outline groups: two prompts, the agent's replies, and two checks under the first. */
export function recordFor(harness: string) {
  const check = (id: string, sub: number, result: string, summary: string) =>
    fact(harness, id, 'tool_report', 2, G - 500 + sub, summary, {
      ordinal_sub: sub,
      result,
      result_source: 'flag',
      source_kind: 'check_run',
      subject: `check:${id}`,
    });
  return [
    fact(
      harness,
      'p1',
      'user_message',
      1,
      G - 600,
      'Add retry with backoff to the webhook handler.',
    ),
    fact(harness, 'a1', 'agent_message', 2, G - 550, 'Adding a retry wrapper.'),
    check('c1', 1, 'failed', 'pytest tests/test_webhook.py'),
    check('c2', 2, 'passed', 'ruff check src'),
    fact(
      harness,
      'p2',
      'user_message',
      3,
      G - 300,
      'Keep the diff small and leave the tests alone.',
    ),
    fact(harness, 'a2', 'agent_message', 4, G - 250, 'Reverting the test edit.'),
  ].filter((row) => harness === 'claude' || row.type === 'user_message');
}

export const COVERAGE = {
  complete: true,
  starts_at: null,
  start_offset: 0,
  end_offset: 4096,
  unread: [],
  notes: [],
  agent_replies: 'read',
  checks_and_files: 'read',
};

const counts = (over: Record<string, number> = {}) => ({
  checks: 0,
  checks_failed: 0,
  files: 0,
  agent_messages: 0,
  subagent_entries: 0,
  ...over,
});

export function claudeOutline(over: Record<string, unknown> = {}) {
  return {
    state: 'ok',
    made_by: 'compass',
    basis: 'grouping',
    reason: null,
    harness: 'claude',
    coverage: COVERAGE,
    more_blocks: 0,
    blocks: [
      {
        prompt: {
          fact_id: 'p1',
          title: 'Add retry with backoff to the webhook handler.',
          at: G - 600,
        },
        span: { first: 'p1', last: 'c2', entries: 4, from_at: G - 600, to_at: G - 498 },
        counts: counts({ checks: 2, checks_failed: 1, files: 3, agent_messages: 1 }),
        failures: [{ fact_id: 'c1', title: 'pytest tests/test_webhook.py', result: 'failed' }],
        checks: [
          { fact_id: 'c1', title: 'pytest tests/test_webhook.py', result: 'failed' },
          { fact_id: 'c2', title: 'ruff check src', result: 'passed' },
        ],
        folders: [
          { folder: 'src/webhook', files: 2 },
          { folder: 'tests', files: 1 },
        ],
      },
      {
        prompt: {
          fact_id: 'p2',
          title: 'Keep the diff small and leave the tests alone.',
          at: G - 300,
        },
        span: { first: 'p2', last: 'a2', entries: 2, from_at: G - 300, to_at: G - 250 },
        counts: counts({ agent_messages: 1 }),
        failures: [],
        checks: [],
        folders: [],
      },
    ],
    ...over,
  };
}

export function codexOutline() {
  return {
    ...claudeOutline(),
    harness: 'codex',
    coverage: {
      ...COVERAGE,
      agent_replies: 'not_read',
      checks_and_files: 'not_admitted',
      notes: ['codex_agent_words_not_admitted', 'codex_checks_and_files_not_admitted'],
    },
    blocks: [
      {
        prompt: {
          fact_id: 'p1',
          title: 'Add retry with backoff to the webhook handler.',
          at: G - 600,
        },
        span: { first: 'p1', last: 'p1', entries: 1, from_at: G - 600, to_at: G - 600 },
        counts: counts(),
        failures: [],
        checks: [],
        folders: [],
      },
      {
        prompt: {
          fact_id: 'p2',
          title: 'Keep the diff small and leave the tests alone.',
          at: G - 300,
        },
        span: { first: 'p2', last: 'p2', entries: 1, from_at: G - 300, to_at: G - 300 },
        counts: counts(),
        failures: [],
        checks: [],
        folders: [],
      },
    ],
  };
}

export const unsupportedOutline = (harness: string) => ({
  state: 'unsupported',
  made_by: 'compass',
  basis: 'grouping',
  reason: 'no_paged_record',
  harness,
  coverage: null,
  blocks: [],
  more_blocks: 0,
});

/* `outline` is what the focused context answers with: a payload, `'stall'` to hold the answer, `'error'` to
   fail it, or `null` to answer without one. */
export interface OutlineScript {
  outline: unknown;
  served: number;
  release: (() => void) | null;
}

export const script: OutlineScript = { outline: null, served: 0, release: null };

export function OutlinePage({
  harness = 'claude',
  outline,
  ended = false,
}: {
  readonly harness?: string;
  readonly outline: unknown;
  readonly ended?: boolean;
}) {
  const [shell] = useState(() => {
    script.outline = outline;
    script.served = 0;
    script.release = null;
    const history = fakeRouterEnvironment(`#n=session:demo:${harness}:s1`);
    let generation = G;
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    const record = recordFor(harness);
    return createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      router: createRouter(history.env),
      provider: () => fakeBackend(),
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      fetch: async (url) => {
        if (url.startsWith('/api/data')) {
          script.served += 1;
          return json({
            generated: generation++,
            annotate: true,
            harnesses: [
              { key: 'claude', label: 'Claude Code' },
              { key: 'codex', label: 'Codex' },
              { key: 'pi', label: 'Pi' },
            ],
            sessions: [
              {
                harness,
                sid: 's1',
                project: 'demo',
                project_key: '/demo',
                title: 'Synthetic outline session',
                state: ended ? 'idle' : 'working',
                started_at: G - 3600,
                ...(ended ? { ended_at: G - 60 } : {}),
              },
            ],
          });
        }
        if (url.startsWith('/api/project-context')) {
          const focused = url.includes('session=');
          if (!focused) return json({ semantic: { facts: [] }, sources: { work: {} } });
          if (script.outline === 'stall')
            await new Promise<void>((resolve) => {
              script.release = resolve;
            });
          if (script.outline === 'error') return json({ error: 'unreadable' }, 500);
          return json({
            semantic: { facts: [] },
            sources: {
              work: { tool_reports: [] },
              ...(script.outline && script.outline !== 'stall' ? { outline: script.outline } : {}),
            },
          });
        }
        if (url.startsWith('/api/annotations'))
          return json({ annotations: [], intent_revision: 'r1' });
        if (url.startsWith('/api/session-record')) {
          if (harness === 'pi')
            return json({
              state: 'unsupported',
              session: { harness, sid: 's1' },
              entries: [],
              next: null,
              reached_start: true,
              bound: null,
              scanned_bytes: 0,
              kinds: [],
            });
          return json({
            state: 'ok',
            session: { harness, sid: 's1' },
            entries: [...record].reverse(),
            next: null,
            reached_start: true,
            bound: null,
            scanned_bytes: 4096,
            kinds: ['user_message', 'agent_message', 'tool_report'],
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
  return (
    <>
      <App shell={shell} />
      <button type="button" onClick={() => void shell.runtime.refresh()}>
        Simulate board poll
      </button>
    </>
  );
}
