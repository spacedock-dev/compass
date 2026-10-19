/*
 * The scripted board the Drift browser tests drive.
 *
 * The document and every module come from the real backend (the React page over `intent_backend.py`), so the
 * page is the real page. What a reading says, what is running, what the
 * record holds and what the receiver is are SCRIPTED: `/api/data` and `/api/project-context` are answered
 * from the real backend's body with the Drift fields replaced, and the routes that could reach a model or a
 * correction (`/api/reading`, `/api/reading/cancel`, `/api/correction`, `/api/correction/copied`) are
 * answered by a handler this file owns and never reach any backend.
 *
 * No model is ever called: nothing here can start one, and a POST nobody scripted is refused with a 404 so a
 * request the page should not make fails loudly instead of reaching the real route.
 */

export const SID = 'intent-2';
export const HARNESS = 'claude';

export const ROUTE = {
  provider: 'claude',
  harness: 'claude',
  destination: 'api',
  words_destination: 'api',
  label: 'Claude Code',
  model: 'm',
  disclosure: 'This sends the session to Claude Code.',
  disclosure_parts: ['Your saved words.', 'The agent messages.'],
  tool_output: 'Tool output goes to the api.',
};

export const POLICY = {
  consent: true,
  off: false,
  reason: '',
  providers: { claude: true },
  words: { claude: true },
  tool_output: { claude: ['api'] },
  used: 1,
  limit: 10,
};

export const UNCONSENTED = {
  consent: true,
  off: false,
  reason: '',
  providers: { claude: false },
  words: {},
  tool_output: {},
  used: 0,
  limit: 10,
};

export function fact(id, at, extra = {}) {
  return {
    fact_id: id,
    type: 'user_message',
    by: 'person:me',
    summary: `Entry ${id}`,
    at,
    source_session: { harness: HARNESS, sid: SID },
    evidence: { source: 'transcript', confidence: 'exact' },
    ...extra,
  };
}

export const check = (id, at, result, extra = {}) =>
  fact(id, at, {
    type: 'tool_report',
    by: 'agent',
    subject: 'check',
    result,
    result_source: 'passed flag',
    summary: 'pytest',
    ...extra,
  });

/* What a state is: `session` and `payload` are merged over the real board's row and body, `facts` and `work`
   replace the record the page reads, and `routes` answers the POSTs. Everything is relative to the real
   board's own clock, so an age reads the same on every run. */
export function freshScript() {
  return {
    session: {},
    payload: {},
    facts: [],
    work: {},
    contextError: false,
    routes: {},
    posts: [],
  };
}

export const SAVED = (generated) => ({
  annotation_goal: 'Ship the queue worker',
  annotation_goal_why: '',
  annotation_lines_why: '',
  annotation_line_1: 'Tests pass',
  annotation_line_1_source: 'typed',
  annotation_revision: 3,
  annotation_revision_count: 3,
  annotation_at: generated - 600,
  annotation_goal_saved_at: generated - 600,
  annotation_goal_source: '',
  annotation_window_start: generated - 900,
  annotation_settled_through: null,
});

export const ASSESSMENT = (generated, extra = {}) => ({
  revision_read: 3,
  revision_read_at: generated - 600,
  window_start: generated - 900,
  read_at: generated - 300,
  evidence_through: generated - 300,
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
      clause: 'Ship the queue worker',
    },
    line_1: {
      result: 'consistent with the evidence read',
      cites: ['c2'],
      detail: '',
      clause: 'Tests pass',
    },
  },
  ...extra,
});

export const RECORD = (generated) => [
  check('c1', generated - 700, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
  check('c2', generated - 650, 'passed'),
];

/* A poll can still be inside one of these handlers when the proof closes its context. Playwright then rejects the
   handler's own fetch or fulfill with a "disposed" or "closed" error that nothing awaits, and Node ends the process
   on an unhandled rejection, which failed the shipped-bundle drift proof on hosted runners. Only that closing error
   is set aside here; any other failure of a handler still surfaces. */
export const quietWhenClosing = (handler) => async (route) => {
  try {
    return await handler(route);
  } catch (error) {
    if (
      /Request context disposed|Response has been disposed|has been closed|Target closed/.test(
        String(error?.message),
      )
    )
      return undefined;
    throw error;
  }
};

/* Installs the script on a page's context. The returned object is the script itself, so a test sets a state
   by assigning to it and reloading the page. */
export async function installScript(context, script) {
  const merged = (real) => {
    const body = JSON.parse(JSON.stringify(real));
    body.sessions = (body.sessions || []).map((row) =>
      row.sid === SID && row.harness === HARNESS ? { ...row, ...script.session } : row,
    );
    return { ...body, ...script.payload };
  };
  await context.route(
    '**/api/data*',
    quietWhenClosing(async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      const patched = merged(body);
      await route.fulfill({ response, body: JSON.stringify(patched) });
    }),
  );
  await context.route(
    '**/api/project-context*',
    quietWhenClosing(async (route) => {
      if (script.contextError) return route.fulfill({ status: 500, body: 'unreadable' });
      const response = await route.fetch();
      const body = await response.json().catch(() => ({}));
      const patched = {
        ...body,
        semantic: { ...(body.semantic || {}), facts: script.facts },
        sources: {
          ...(body.sources || {}),
          work: { tool_reports: [], line_requests: [], ...script.work },
        },
      };
      await route.fulfill({ response, body: JSON.stringify(patched) });
    }),
  );
  await context.route(
    '**/api/session-record*',
    quietWhenClosing(async (route) => {
      const query = new URL(route.request().url()).searchParams;
      const key = query.get('session') ?? ':';
      const split = key.indexOf(':');
      const facts = script.facts
        .filter((fact) => ['user_message', 'agent_message'].includes(fact.type))
        .sort((a, b) => b.at - a.at || String(a.fact_id).localeCompare(String(b.fact_id)));
      const before = Number(query.get('before') ?? 0);
      const limit = Math.max(1, Math.min(50, Number(query.get('limit') ?? 50)));
      const entries = facts.slice(before, before + limit);
      const reached = before + entries.length >= facts.length;
      await route.fulfill({
        status: script.contextError ? 500 : 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { harness: key.slice(0, split), sid: key.slice(split + 1) },
          entries,
          next: reached ? null : String(before + limit),
          reached_start: reached,
          bound: null,
          scanned_bytes: 0,
          kinds: ['user_message', 'agent_message'],
          state: 'ok',
        }),
      });
    }),
  );
  const scripted = [
    '/api/reading',
    '/api/reading/cancel',
    '/api/correction',
    '/api/correction/copied',
  ];
  await context.route(
    (url) => scripted.includes(url.pathname),
    async (route) => {
      const request = route.request();
      if (request.method() !== 'POST') return route.fallback();
      const path = new URL(request.url()).pathname;
      let body = null;
      try {
        body = JSON.parse(request.postData() || 'null');
      } catch {
        body = null;
      }
      script.posts.push({ path, body });
      const handler = script.routes[path];
      if (!handler) {
        return route.fulfill({ status: 404, body: 'no model, correction or cancel was scripted' });
      }
      const answer = await handler(body);
      if (answer === 'hold') return new Promise(() => undefined);
      if (answer === 'abort') return route.abort();
      return route.fulfill({
        status: answer.status ?? 200,
        contentType: 'application/json',
        body: typeof answer.body === 'string' ? answer.body : JSON.stringify(answer.body ?? {}),
      });
    },
  );
}

export const postsTo = (script, path) => script.posts.filter((post) => post.path === path);
