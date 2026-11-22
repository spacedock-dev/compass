/* Boards and project-context reads for the project differentials: the shapes the cockpit meets (Spacedock
   strips with entities, delegated workers and what they returned, a context holding facts, trail heads
   and an attention projection) and the ones it must survive (duplicate labels, the empty label, one sid
   under two harnesses, an ended session with no end stamp, a project with no plans or no sessions,
   unicode, a field present with the wrong type). Seeded, so a failing board is reproducible by number.
   Every value is JSON-representable. */

/* The base generator the boards are layered on, handed in rather than imported, so this file stands alone:
   Node's type stripping loads it from a browser script as it loads it from a unit test, and neither needs
   a module resolver. */
export type Rng = () => number;
export interface BaseGenerators {
  readonly genPayload: (
    seed: number,
    options?: { wellFormed?: boolean },
  ) => Record<string, unknown>;
  readonly mulberry32: (seed: number) => Rng;
  readonly pick: <T>(rnd: Rng, items: readonly T[]) => T;
}

export const projectStatusBoard = {
  generated: 1000,
  sessions: [
    { sid: 'working', title: 'Running checks', state: 'working', active: true },
    { sid: 'stopped', title: 'Recorded stop', state: 'idle', finished_at: 980 },
    { sid: 'scan', title: 'Scan-only session', state: 'idle', acquisition: 'scan-only' },
  ].map((row) => ({ harness: 'claude', project: 'rollup', last_activity: 990, ...row })),
};

export function makeBoards({ genPayload, mulberry32, pick }: BaseGenerators) {
  const chance = (rnd: Rng, p: number): boolean => rnd() < p;
  const int = (rnd: Rng, low: number, high: number): number =>
    low + Math.floor(rnd() * (high - low + 1));

  type Json = Record<string, unknown>;

  const WORKFLOWS = ['build', 'ship', '', '  ', 'ünï flow', 'a/b'] as const;
  const STAGES = ['plan', 'build', 'review', 'ship', '', '  ', 'ünï'] as const;
  const SLUGS = ['alpha', 'beta', 'gamma', '', 'ünï-slug', 'alpha'] as const;
  const WORDS = [
    'Ship the retry queue',
    'thanks',
    'https://example.com/x',
    'please send a progress report',
    'Use the browser works sandbox access',
    'Fix the build',
    '  ',
    'Ünï direction',
    'Make the drain order stable',
  ] as const;

  function genStrip(rnd: Rng): unknown {
    if (chance(rnd, 0.08)) return pick(rnd, [null, 'x', 4, []]);
    const entities: unknown[] = [];
    for (let index = 0; index < int(rnd, 0, 4); index += 1) {
      entities.push(
        chance(rnd, 0.08)
          ? pick(rnd, [null, 'e'])
          : {
              slug: pick(rnd, SLUGS),
              stage: pick(rnd, STAGES),
              cycle: pick(rnd, ['', '2', ' 3 ', undefined, 4]),
              live: pick(rnd, [true, false, true, 'yes', undefined]),
            },
      );
    }
    return {
      workflow: pick(rnd, WORKFLOWS),
      goal: pick(rnd, ['Ship it', '', '  ', undefined, 'Ünï goal']),
      stages: chance(rnd, 0.1) ? pick(rnd, ['x', null, 3]) : STAGES.filter(() => chance(rnd, 0.6)),
      entities: chance(rnd, 0.06) ? pick(rnd, ['x', null]) : entities,
    };
  }

  function genHierarchy(rnd: Rng, generated: number | null): unknown {
    if (chance(rnd, 0.5)) return undefined;
    const out: unknown[] = [];
    for (let index = 0; index < int(rnd, 0, 3); index += 1) {
      out.push({
        name: pick(rnd, ['worker', '', 'Ünï', undefined, 'lens']),
        active: pick(rnd, [true, false, undefined]),
        depth: pick(rnd, [1, 2, 9, 0, 'x', undefined]),
        parent_name: pick(rnd, [undefined, 'lead', '']),
        observer_sid: pick(rnd, ['o1', 'o2', '', undefined]),
        assignment: pick(rnd, ['Review the diff', '', undefined, 'Write tests']),
        assignment_status: pick(rnd, [
          undefined,
          'exact parent dispatch',
          'structured dispatch',
          'derived',
        ]),
        work_item_id: pick(rnd, ['w1', 'w2', '', undefined]),
        workflow_entity: pick(rnd, ['alpha', '', undefined]),
        workflow_stage: pick(rnd, ['build', '', undefined]),
        workflow_binding: pick(rnd, ['spacedock', '', undefined]),
        started_at: generated === null ? null : generated - 30,
      });
    }
    return out;
  }

  function genEvents(rnd: Rng, generated: number | null): unknown {
    if (chance(rnd, 0.6)) return undefined;
    const base = generated ?? 1000;
    const out: unknown[] = [];
    for (let index = 0; index < int(rnd, 0, 3); index += 1) {
      out.push(
        chance(rnd, 0.1)
          ? pick(rnd, [null, 'e'])
          : {
              kind: pick(rnd, [
                'subagent_complete',
                'subagent_complete',
                'subagent_start',
                undefined,
              ]),
              name: pick(rnd, ['lens', '', 'Ünï', undefined]),
              at: pick(rnd, [base - 20, base - 900, base - 5000, 0, 'x', undefined]),
              assignment: pick(rnd, ['Review the diff', '  ', undefined, 4, 'Fix it']),
              result: pick(rnd, ['Done', '', undefined, '  ', 7]),
              result_summary: pick(rnd, ['Summary', undefined, '']),
              source: pick(rnd, ['child lifecycle', 'source unavailable', undefined, '']),
            },
      );
    }
    return out;
  }

  /* A board: the base generator's sessions, given the project fields and published activity the cockpit
   reads. Stamps are made relative to the board's own clock, because the base generator's are fixed numbers
   that put every age at zero. */
  function genBoard(seed: number): Json {
    const rnd = mulberry32(seed * 7919 + 13);
    const payload = genPayload(seed, { wellFormed: true });
    const generated = typeof payload['generated'] === 'number' ? payload['generated'] : null;
    const base = generated ?? 1000;
    const sessions = Array.isArray(payload['sessions']) ? (payload['sessions'] as Json[]) : [];
    const keyByLabel = new Map<string, string>();
    // One crowded project, so a row past its member cap is met.
    if (chance(rnd, 0.4)) {
      const crowded = pick(rnd, ['alpha/app', 'gamma', '']);
      for (const row of sessions) if (chance(rnd, 0.75)) row['project'] = crowded;
    }
    for (const row of sessions) {
      const label = typeof row['project'] === 'string' ? row['project'] : '';
      if (chance(rnd, 0.5)) {
        if (!keyByLabel.has(label) || chance(rnd, 0.15))
          keyByLabel.set(label, pick(rnd, ['/repo/a', '/repo/b', '']));
        row['project_key'] = keyByLabel.get(label);
      }
      if (chance(rnd, 0.4))
        row['project_name'] = pick(rnd, ['alpha/app', '', '  ', 'a/b/c', 'ünï/çødé']);
      if (chance(rnd, 0.7))
        row['last_activity'] = pick(rnd, [base - 3, base - 90, base - 700, base - 90_000, null, 0]);
      if (chance(rnd, 0.5)) {
        const strips = Array.from({ length: int(rnd, 1, 3) }, () => genStrip(rnd));
        row['spacedock'] = chance(rnd, 0.9)
          ? {
              workflows: strips,
              role: pick(rnd, ['first-officer', 'ensign', 'other', undefined]),
            }
          : pick(rnd, [null, 'x', {}]);
      }
      if (chance(rnd, 0.5)) {
        row['total'] = pick(rnd, [0, 3, 5, -2, 'x', null, 7.5]);
        row['done'] = pick(rnd, [0, 1, 2, 9, -1, 'x', null]);
      }
      if (chance(rnd, 0.4))
        row['last_output'] = pick(rnd, [
          'Fixed it\nsecond line',
          '',
          '  ',
          'x'.repeat(260),
          'Done.',
          4,
        ]);
      const hierarchy = genHierarchy(rnd, generated);
      if (hierarchy !== undefined) row['subagent_hierarchy'] = hierarchy;
      const events = genEvents(rnd, generated);
      if (events !== undefined) row['subagent_events'] = events;
      if (chance(rnd, 0.3)) row['work_item_id'] = pick(rnd, ['w1', 'w2', '']);
    }
    return payload;
  }

  function sessionRef(rnd: Rng, payload: Json): unknown {
    const sessions = Array.isArray(payload['sessions']) ? (payload['sessions'] as Json[]) : [];
    if (sessions.length === 0 || chance(rnd, 0.15))
      return pick(rnd, [
        undefined,
        null,
        {},
        { harness: 'claude' },
        { harness: 'ghost', sid: 'none' },
      ]);
    const row = pick(rnd, sessions);
    return { harness: row['harness'], sid: row['sid'] };
  }

  function genFacts(rnd: Rng, payload: Json, base: number): unknown[] {
    const facts: unknown[] = [];
    for (let index = 0; index < int(rnd, 0, 9); index += 1) {
      if (chance(rnd, 0.05)) {
        facts.push(pick(rnd, [null, 'x', 3]));
        continue;
      }
      const type = pick(rnd, [
        'user_message',
        'user_message',
        'result',
        'gate_decision',
        'decision',
        'stage_transition',
        'prepared_dispatch',
        'work_result',
        'bogus',
      ]);
      facts.push({
        fact_id: pick(rnd, ['f' + String(index), 'f' + String(index), '', undefined, 'dup']),
        at: pick(rnd, [base - 10 * index, base - 4000 - index, 0, 'x', undefined]),
        type,
        summary: pick(rnd, WORDS),
        detail: pick(rnd, [
          undefined,
          'Fixed the thing, live. Checkpoint: abcdef1',
          'Review changed the course:\n- one finding\n- two finding\n\nrest',
          'Done live at 1234567',
          '1. **Review changed the course**: \n * only',
        ]),
        stage: pick(rnd, STAGES),
        target_stage: pick(rnd, ['ship', '', undefined]),
        source_kind: pick(rnd, ['transcript', '', undefined]),
        scope: pick(rnd, ['project', 'session', '', undefined]),
        by: pick(rnd, ['person:captain', 'agent', undefined]),
        decision: pick(rnd, ['approve', '', undefined]),
        application_state: pick(rnd, [
          'pending',
          'unspent',
          'consumed',
          'applied',
          'superseded',
          '',
          'odd',
          undefined,
        ]),
        work_item_id: pick(rnd, ['w1', 'w2', 'w3', '', undefined]),
        source_session: sessionRef(rnd, payload),
        evidence: pick(rnd, [
          { source: 'transcript', confidence: 'exact' },
          { source: 'transcript', confidence: 'exact' },
          { source: '', confidence: 'derived' },
          { confidence: 'exact' },
          null,
          'x',
        ]),
        intent_promoted: pick(rnd, [true, false, undefined]),
        copied: pick(rnd, [true, false, undefined]),
      });
    }
    // One direction the cockpit will accept, often enough that the assignment-from-direction path is met.
    if (chance(rnd, 0.55))
      facts.push({
        fact_id: 'good-direction',
        at: base - 2,
        type: 'user_message',
        summary: pick(rnd, ['ship the retry queue', 'make the drain order stable']),
        source_session: sessionRef(rnd, payload),
        evidence: { source: 'transcript', confidence: 'exact' },
      });
    if (chance(rnd, 0.5))
      facts.push({
        fact_id: 'good-result',
        at: base - 1,
        type: 'result',
        summary: 'Fixed and live',
        detail: 'Fixed the drain, live. Checkpoint: abcdef1',
        work_item_id: pick(rnd, ['w1', 'w2']),
        source_session: sessionRef(rnd, payload),
        evidence: { source: 'transcript', confidence: 'exact' },
      });
    return facts;
  }

  /* A project context read as the server answers it. `shape` picks how complete it is, because the
   cockpit's absence sentences hang on which parts exist. */
  function genContext(seed: number, payload: Json): Json | null {
    const rnd = mulberry32(seed * 104729 + 7);
    if (chance(rnd, 0.1)) return null;
    const generated = typeof payload['generated'] === 'number' ? payload['generated'] : null;
    const base = generated ?? 1000;
    const projections: Json = {};
    if (chance(rnd, 0.85))
      projections['trail_heads'] = Array.from({ length: int(rnd, 0, 3) }, () => ({
        work_item_id: pick(rnd, ['w1', 'w2', 'w3', '']),
        stage: pick(rnd, STAGES),
        status: pick(rnd, ['current stage', 'prepared', 'requested', 'done']),
        dispatch_count: pick(rnd, [0, 1, 2, 3]),
      }));
    if (chance(rnd, 0.8))
      projections['command_attention'] = Array.from({ length: int(rnd, 0, 3) }, () => ({
        owner: pick(rnd, ['CAPTAIN', 'FO', 'OTHER', undefined]),
        kind: pick(rnd, [
          'authorize_dispatch',
          'choose_next',
          'revise_plan',
          'stage_link_required',
          'gate',
          '',
        ]),
        question: pick(rnd, ['Approve the plan?', '', undefined, '  ']),
        label: pick(rnd, ['resolve this', 'refresh workflow discovery', '']),
        blocked_step: pick(rnd, ['merge', '', undefined]),
        evidence: pick(rnd, [{ source: 'ask registry', confidence: 'exact' }, undefined, 'x', {}]),
      }));
    projections['command_attention_coverage'] = pick(rnd, [
      { state: 'complete', scanned: 2, total: 2, source: 'active-session attention scan' },
      { state: 'incomplete', scanned: 1, total: 3, omitted: 2 },
      { state: 'incomplete', scanned: 1, total: 3, omitted: -1 },
      { state: 'complete', scanned: 3, total: 2 },
      { state: 'weird', scanned: 1, total: 1 },
      { state: 'complete', scanned: 1, total: 1 },
      undefined,
      'x',
    ]);
    // A direction and the result it led to, paired by the steering episode: the shape an episode draws as
    // "Direction · ..." beside its own words.
    const paired = chance(rnd, 0.4);
    projections['operator_intents'] = [
      { projection_id: 'i1', derived_from: paired ? 'pair-direction' : 'f1', at: base - 5 },
    ];
    projections['steering_episodes'] = [
      { adaptation_fact: paired ? 'pair-result' : 'f2', intent_id: 'i1' },
    ];
    const facts = chance(rnd, 0.92) ? genFacts(rnd, payload, base) : undefined;
    if (paired && facts)
      facts.push(
        {
          fact_id: 'pair-direction',
          at: base - 50,
          type: 'user_message',
          summary: 'Make the drain order stable',
          work_item_id: 'w1',
          source_session: sessionRef(rnd, payload),
          evidence: { source: 'transcript', confidence: 'exact' },
        },
        {
          fact_id: 'pair-result',
          at: base - 10,
          type: 'result',
          summary: 'Drain order stable',
          detail: 'Fixed the drain, live. Checkpoint: abcdef12',
          work_item_id: 'w1',
          source_session: sessionRef(rnd, payload),
          evidence: { source: 'transcript', confidence: 'exact' },
        },
      );
    const semantic: Json = {
      // A `facts` that is not a list stops the legacy Course builder, so the generator never makes one.
      facts,
      work_items: Array.from({ length: int(rnd, paired ? 1 : 0, 3) }, (_, index) => ({
        work_item_id: 'w' + String(index + 1),
        label: pick(rnd, ['ship-feature', 'fix_bug', '', 'ünï-task']),
        kind: pick(rnd, ['workflow_item', 'task', '']),
      })),
      projections,
      history: pick(rnd, [
        { reason: '' },
        { reason: 'History is off.' },
        { window_sec: 3600 },
        { window_sec: 90 },
        {},
      ]),
    };
    const context: Json = {
      semantic: chance(rnd, 0.92) ? semantic : pick(rnd, [undefined, null]),
      workflow_discovery: pick(rnd, [
        {
          state: 'observed',
          workflows: [
            { workflow: 'build', goal: 'Ship it', stages: ['plan', 'ship'] },
            { workflow: '' },
          ],
        },
        { state: 'observed', workflows: [] },
        { state: 'none' },
        { state: 'unavailable', reason: 'no permission', source: 'spacedock discovery' },
        { state: 'error', reason: 'timed out' },
        { state: 'loading' },
        undefined,
      ]),
      sources: pick(rnd, [
        undefined,
        {},
        { observer: { unavailable: [{ reason: 'observer offline' }] } },
        { git: { unavailable: [{ reason: 'no repository' }, {}] }, claude: { unavailable: 'x' } },
      ]),
      child_assignments: pick(rnd, [
        undefined,
        [],
        [
          {
            observer_sid: 'o1',
            name: 'lens',
            assignment: 'Review the diff',
            source: 'child observer snapshot',
            snapshot_status: 'derived',
            workflow_entity: 'alpha',
          },
          // A row that is not a record stops the legacy page's lane builder, so the generator never makes one
          // and a unit test holds the port to skipping it.
          { observer_sid: 'o2', name: 'second' },
        ],
      ]),
    };
    return JSON.parse(JSON.stringify(context)) as Json;
  }

  /* Boards built by hand for the states a random board rarely reaches: a calm project the first officer is
   simply driving, one where nothing is running and nothing is asked, one session with a plan and a
   workflow, and one waiting on the captain with an exact question. Each is a board and the context read
   that goes with it. */
  interface Scenario {
    readonly name: string;
    readonly board: Json;
    readonly context: Json | null;
  }

  const COMPLETE = {
    state: 'complete',
    scanned: 2,
    total: 2,
    source: 'active-session attention scan',
  };

  function calmContext(extra: Json = {}): Json {
    return {
      semantic: {
        facts: [],
        work_items: [{ work_item_id: 'w1', label: 'ship-feature', kind: 'workflow_item' }],
        projections: {
          trail_heads: [{ work_item_id: 'w1', stage: 'build', status: 'current stage' }],
          command_attention: [],
          command_attention_coverage: COMPLETE,
        },
        history: { window_sec: 3600 },
      },
      workflow_discovery: {
        state: 'observed',
        workflows: [{ workflow: 'build', goal: 'Ship it', stages: ['plan', 'build'] }],
      },
      ...extra,
    };
  }

  function session(sid: string, project: string, fields: Json = {}): Json {
    return {
      harness: 'claude',
      sid,
      session: sid,
      project,
      title: `Session ${sid}`,
      state: 'working',
      active: true,
      last_activity: 995,
      ...fields,
    };
  }

  const HARNESSES = [
    {
      key: 'claude',
      label: 'Claude Code',
      reports_needs_input: true,
      reports_rate: true,
      discovered: true,
    },
  ];

  function scenarios(): Scenario[] {
    return [
      {
        name: 'calm',
        board: {
          generated: 1000,
          harnesses: HARNESSES,
          ask: true,
          asks: [],
          sessions: [session('a', 'calm/app', { rate_per_min: 900 }), session('b', 'calm/app')],
        },
        context: calmContext(),
      },
      {
        name: 'ended only',
        board: {
          generated: 1000,
          harnesses: HARNESSES,
          ask: true,
          asks: [],
          sessions: [
            session('a', 'done/app', {
              ended_at: 990,
              state: 'working',
              finished_at: 990,
              dirty: false,
            }),
          ],
        },
        context: calmContext(),
      },
      {
        name: 'single session with a plan',
        board: {
          generated: 1000,
          harnesses: HARNESSES,
          ask: true,
          asks: [],
          sessions: [
            session('a', 'plan/app', {
              // Quiet for 700 seconds while the plan calls its entity live: stalled, by the page's own threshold.
              last_activity: 300,
              total: 4,
              done: 1,
              tasks: [{ id: '1', subject: 'Write the test', status: 'completed' }],
              spacedock: {
                role: 'first-officer',
                workflows: [
                  {
                    workflow: 'build',
                    goal: 'Ship it',
                    stages: ['plan', 'build'],
                    entities: [
                      { slug: 'alpha', stage: 'build', live: true, cycle: '2' },
                      { slug: 'beta', stage: 'plan', live: false },
                    ],
                  },
                ],
              },
            }),
          ],
        },
        context: calmContext(),
      },
      {
        name: 'a long course',
        board: {
          generated: 1000,
          harnesses: HARNESSES,
          ask: true,
          asks: [],
          sessions: [
            session('a', 'course/app', {
              subagent_hierarchy: [
                {
                  name: 'lens',
                  active: true,
                  observer_sid: 'o1',
                  assignment: 'Review the diff',
                  assignment_status: 'exact parent dispatch',
                  work_item_id: 'w1',
                },
              ],
            }),
            session('b', 'course/app', { state: 'idle', last_activity: 400 }),
          ],
        },
        context: calmContext({
          semantic: {
            facts: [
              ...Array.from({ length: 10 }, (_, index) => ({
                fact_id: `s${String(index)}`,
                at: 100 + index,
                type: 'stage_transition',
                stage: `stage-${String(index)}`,
                summary: `Moved to stage ${String(index)}`,
                work_item_id: 'w1',
                source_session: { harness: 'claude', sid: 'a' },
                evidence: { source: 'workflow state', confidence: 'exact' },
              })),
              {
                fact_id: 'rev',
                at: 300,
                type: 'result',
                summary: 'Reviewed',
                detail: 'Review changed the course:\n- drop the cache\n- add the retry',
                work_item_id: 'w1',
                source_session: { harness: 'claude', sid: 'a' },
                evidence: { source: 'review', confidence: 'exact' },
              },
              {
                fact_id: 'dir',
                at: 310,
                type: 'user_message',
                summary: 'Land it behind a flag',
                work_item_id: 'w1',
                source_session: { harness: 'claude', sid: 'a' },
                evidence: { source: 'transcript', confidence: 'exact' },
              },
              {
                fact_id: 'live',
                at: 320,
                type: 'result',
                summary: 'Shipped',
                detail: 'Fixed the drain, live. Checkpoint: abcdef12',
                work_item_id: 'w1',
                source_session: { harness: 'claude', sid: 'a' },
                evidence: { source: 'transcript', confidence: 'exact' },
              },
              {
                fact_id: 'gate',
                at: 330,
                type: 'gate_decision',
                scope: 'project',
                by: 'person:captain',
                decision: 'approve',
                stage: 'review',
                application_state: 'consumed',
                target_stage: 'ship',
                work_item_id: 'w1',
                summary: 'approve',
                evidence: { source: 'entity gate', confidence: 'exact' },
              },
              {
                fact_id: 'other',
                at: 340,
                type: 'user_message',
                summary: 'Keep the cache after all',
                intent_promoted: true,
                source_session: { harness: 'claude', sid: 'b' },
                evidence: { source: 'transcript', confidence: 'exact' },
              },
            ],
            work_items: [{ work_item_id: 'w1', label: 'ship-feature', kind: 'workflow_item' }],
            projections: {
              trail_heads: [{ work_item_id: 'w1', stage: 'build', status: 'current stage' }],
              command_attention: [],
              command_attention_coverage: COMPLETE,
              operator_intents: [{ projection_id: 'i1', derived_from: 'dir', at: 310 }],
              steering_episodes: [{ adaptation_fact: 'live', intent_id: 'i1' }],
            },
            history: { window_sec: 3600 },
          },
        }),
      },
      {
        name: 'waiting on the captain',
        board: {
          generated: 1000,
          harnesses: HARNESSES,
          ask: true,
          asks: [
            {
              id: 'q1',
              harness: 'claude',
              session_id: 'a',
              project: 'wait/app',
              question: 'Approve the plan?',
              options: ['Yes', 'No'],
              age_sec: 120,
            },
          ],
          sessions: [
            session('a', 'wait/app', {
              state: 'needs_input',
              blocked_since: 880,
              focusable: true,
              resume_id: 'abc-123',
            }),
            session('b', 'wait/app', { state: 'idle', last_activity: 300 }),
          ],
        },
        context: calmContext({
          semantic: {
            facts: [
              {
                fact_id: 'd1',
                at: 900,
                type: 'gate_decision',
                scope: 'project',
                by: 'person:captain',
                decision: 'approve',
                stage: 'review',
                application_state: 'pending',
                work_item_id: 'w1',
                evidence: { source: 'entity gate', confidence: 'exact' },
              },
            ],
            work_items: [{ work_item_id: 'w1', label: 'ship-feature', kind: 'workflow_item' }],
            projections: {
              trail_heads: [{ work_item_id: 'w1', stage: 'build', status: 'current stage' }],
              command_attention: [
                {
                  owner: 'CAPTAIN',
                  kind: 'authorize_dispatch',
                  question: 'Authorize the dispatch?',
                  evidence: { source: 'ask registry', confidence: 'exact' },
                },
              ],
              command_attention_coverage: COMPLETE,
            },
            history: { window_sec: 3600 },
          },
        }),
      },
    ];
  }

  /* The board the browser proof serves to both pages: several projects with the states the brief names
     (a plan with a live and a pending entity, the same sid under two harnesses, a session that ended
     without an end stamp, a source gap, a project with no plan, a unicode label, a label that differs
     by whitespace only, an empty label) and a project context read for each project that has one. The
     clock is fixed, so both pages age every stamp the same way. */
  function parityBoard(): { board: Json; contexts: Record<string, Json | null> } {
    const GENERATED = 2000;
    const lead = (extra: Json = {}): Json =>
      session('a-lead', 'alpha/app', {
        project_key: '/repo/alpha',
        project_name: 'alpha/app',
        last_activity: GENERATED - 5,
        rate_per_min: 900,
        total: 4,
        done: 1,
        tasks: [
          { id: '1', subject: 'Write the failing test', status: 'completed' },
          { id: '2', subject: 'Fix the drain order', status: 'in_progress' },
        ],
        instruction: {
          label: 'asked',
          text: 'Drain the retry queue in order',
          at: GENERATED - 300,
        },
        subagent_hierarchy: [
          {
            name: 'lens',
            active: true,
            observer_sid: 'o1',
            assignment: 'Review the diff',
            assignment_status: 'exact parent dispatch',
            work_item_id: 'w1',
          },
        ],
        subagent_events: [
          {
            kind: 'subagent_complete',
            name: 'scout',
            at: GENERATED - 120,
            assignment: 'Map the queue',
            result: 'Mapped',
            source: 'child lifecycle',
          },
        ],
        spacedock: {
          role: 'first-officer',
          workflows: [
            {
              workflow: 'build',
              goal: 'Ship it',
              stages: ['plan', 'build', 'review'],
              entities: [
                { slug: 'alpha', stage: 'build', live: true, cycle: '2' },
                { slug: 'beta', stage: 'plan', live: false },
              ],
            },
          ],
        },
        ...extra,
      });
    const sessions: Json[] = [
      lead(),
      session('a-wait', 'alpha/app', {
        project_key: '/repo/alpha',
        state: 'needs_input',
        blocked_since: GENERATED - 140,
        focusable: true,
        resume_id: 'abc-123',
        title: 'Needs a decision',
        last_activity: GENERATED - 60,
      }),
      session('a-lead', 'alpha/app', {
        harness: 'codex',
        project_key: '/repo/alpha',
        state: 'idle',
        title: 'Same sid under codex',
        last_activity: GENERATED - 300,
      }),
      session('a-ended', 'alpha/app', {
        project_key: '/repo/alpha',
        state: 'working',
        ended_at: GENERATED - 10,
        finished_at: GENERATED - 10,
        dirty: true,
        changed: 3,
        title: 'Ended with uncommitted work',
        last_activity: GENERATED - 10,
      }),
      session('a-gap', 'alpha/app', {
        project_key: '/repo/alpha',
        state: 'idle',
        source_gaps: ['block state'],
        title: 'Part of its store was unreadable',
        last_activity: GENERATED - 900,
      }),
      session('a-quiet', 'alpha/app', {
        project_key: '/repo/alpha',
        state: 'idle',
        title: null,
        last_activity: GENERATED - 1500,
      }),
      session('b-1', 'beta/api', {
        state: 'idle',
        title: 'Idle with output',
        last_activity: GENERATED - 400,
        last_output: 'Fixed the drain\nsecond line',
      }),
      session('b-2', 'beta/api', {
        state: 'idle',
        title: 'Another beta',
        last_activity: GENERATED - 500,
      }),
      session('b-3', 'beta/api ', {
        state: 'idle',
        title: 'A label that differs by a space',
        last_activity: GENERATED - 600,
      }),
      session('u-1', 'ünï/çødé', {
        state: 'idle',
        title: 'Ünï ✓ <b>not markup</b> & "quotes"',
        last_activity: GENERATED - 700,
      }),
      session('c-1', 'calm/app', { last_activity: GENERATED - 4, rate_per_min: 300 }),
      session('e-1', '', {
        state: 'idle',
        title: 'No project label',
        last_activity: GENERATED - 800,
      }),
    ];
    const board: Json = {
      generated: GENERATED,
      window_hours: 24,
      harnesses: [
        ...HARNESSES,
        { key: 'codex', label: 'Codex', reports_needs_input: true, discovered: true },
      ],
      ask: true,
      asks: [
        {
          id: 'q1',
          harness: 'claude',
          session_id: 'a-wait',
          project: 'alpha/app',
          question: 'Approve the retry plan?',
          options: ['Yes', 'No'],
          age_sec: 140,
        },
      ],
      sessions,
    };
    const alpha = calmContext({
      semantic: {
        facts: [
          {
            fact_id: 'dir',
            at: GENERATED - 400,
            type: 'user_message',
            summary: 'Land the retry queue behind a flag',
            work_item_id: 'w1',
            source_session: { harness: 'claude', sid: 'a-lead' },
            evidence: { source: 'transcript', confidence: 'exact' },
          },
          {
            fact_id: 'rev',
            at: GENERATED - 300,
            type: 'result',
            summary: 'Reviewed',
            detail: 'Review changed the course:\n- drop the cache\n- add the retry',
            work_item_id: 'w1',
            source_session: { harness: 'claude', sid: 'a-lead' },
            evidence: { source: 'review', confidence: 'exact' },
          },
          {
            fact_id: 'live',
            at: GENERATED - 200,
            type: 'result',
            summary: 'Shipped',
            detail: 'Fixed the drain, live. Checkpoint: abcdef12',
            work_item_id: 'w1',
            source_session: { harness: 'claude', sid: 'a-lead' },
            evidence: { source: 'transcript', confidence: 'exact' },
          },
          {
            fact_id: 'gate',
            at: GENERATED - 100,
            type: 'gate_decision',
            scope: 'project',
            by: 'person:captain',
            decision: 'approve',
            stage: 'review',
            application_state: 'pending',
            work_item_id: 'w1',
            summary: 'approve',
            evidence: { source: 'entity gate', confidence: 'exact' },
          },
        ],
        work_items: [{ work_item_id: 'w1', label: 'ship-feature', kind: 'workflow_item' }],
        projections: {
          trail_heads: [{ work_item_id: 'w1', stage: 'build', status: 'current stage' }],
          command_attention: [
            {
              owner: 'CAPTAIN',
              kind: 'authorize_dispatch',
              question: 'Authorize the dispatch?',
              evidence: { source: 'ask registry', confidence: 'exact' },
            },
          ],
          command_attention_coverage: COMPLETE,
          operator_intents: [{ projection_id: 'i1', derived_from: 'dir', at: GENERATED - 400 }],
          steering_episodes: [{ adaptation_fact: 'live', intent_id: 'i1' }],
        },
        history: { window_sec: 3600 },
      },
      child_assignments: [
        {
          observer_sid: 'o1',
          name: 'lens',
          assignment: 'Review the diff',
          source: 'child observer snapshot',
        },
      ],
    });
    return {
      board,
      contexts: {
        '/repo/alpha': alpha,
        'beta/api': null,
        'calm/app': calmContext(),
        'ünï/çødé': null,
      },
    };
  }

  return { genBoard, genContext, scenarios, parityBoard };
}

export type Scenario = ReturnType<ReturnType<typeof makeBoards>['scenarios']>[number];
