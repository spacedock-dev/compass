/* The board behind the Sessions search and filters sign-off stories and `filters.test.ts`: twelve rows worked
   through `groupSessions` by hand (docs/design-sessions-search.md). The clock is local noon, so Today and
   Yesterday agree on a desk in any time zone and on UTC CI.

   Derived totals the stories assert:
   - Active now holds A, D, B and C; Recent history the other eight.
   - State: Waiting 1, Working 2, Idle 7, Ended 1, State not published 1.
   - Started: Today 5, Yesterday 3, not published 4.
   - Project: recce/compass 6, compass 2 (two keys), projects/pendulum-of-despair 2, recce-cloud-infra 1,
     the empty label 1.
   - Drift: recorded 1 (D), checked 1 (K), not checked 10. */

const local = (dayOffset: number, hours: number, minutes = 0): number =>
  new Date(2030, 0, 15 + dayOffset, hours, minutes).getTime() / 1000;

export const GENERATED = local(0, 12);
export const at = local;

export const SIDS = {
  A: 'a1f0c2d9e8b7',
  B: 'b2e1d3c4a5f6',
  C: 'c9d2e7b1f0a3',
  D: 'd5c4b3a2e1f0',
  E: 'e6f5a4b3c2d1',
  F: 'f7e6d5c4b3a2',
  G: '0a1b2c3d4e5f',
  H: '1b2c3d4e5f6a',
  I: '2c3d4e5f6a7b',
  J: '3d4e5f6a7b8c',
  K: '4e5f6a7b8c9d',
  L: '5f6a7b8c9d0e',
} as const;

const HARNESSES = [
  { key: 'claude', label: 'Claude Code', reports_needs_input: true },
  {
    key: 'codex',
    label: 'Codex',
    reports_needs_input: true,
    reports_needs_input_when: 'where approvals are enabled',
  },
  { key: 'gemini', label: 'Gemini', reports_needs_input: false },
  { key: 'cursor', label: 'Cursor', reports_needs_input: true },
  {
    key: 'pi',
    label: 'Pi',
    reports_needs_input: true,
    reports_needs_input_when:
      'extension UI prompts in persisted sessions; installed adapter on Pi 0.85.1 required; excludes startup trust; restart loses standing waits',
  },
  { key: 'goose', label: 'Goose', reports_needs_input: false },
  {
    key: 'opencode',
    label: 'OpenCode',
    reports_needs_input: true,
    reports_needs_input_when: 'permission prompts through the installed plugin',
  },
].map((row) => ({ ...row, discovered: true, reports_rate: true, error: null }));

const OTHERS = [
  {
    key: 'droid',
    label: 'Droid',
    discovered: true,
    reports_needs_input: false,
    error: 'store could not be read',
  },
  { key: 'copilot', label: 'Copilot', discovered: false, reports_needs_input: true, error: null },
  {
    key: 'antigravity',
    label: 'Antigravity',
    discovered: false,
    reports_needs_input: false,
    error: null,
  },
];

/* A stored reading of K that finds nothing departing, made against the words K holds now. */
const READING_K = {
  revision_read: 1,
  revision_read_at: local(0, 7),
  window_start: local(0, 6, 45),
  read_at: local(0, 7, 35),
  evidence_through: local(0, 7, 30),
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
      result: 'consistent with the evidence read',
      cites: ['e1'],
      detail: '',
      clause: 'Cut the 2.4 release',
    },
  },
};

export interface FixtureOptions {
  readonly generated?: number;
  readonly annotate?: boolean;
  /** Row B has gone quiet since the first board. */
  readonly bIdle?: boolean;
  /** `?all=1`: three older rows the default window would not load. */
  readonly showAll?: boolean;
  /** Annotations on, but the annotation store could not be read. */
  readonly unreadable?: boolean;
  /** Sessions the reader marked handled, which the server leaves off the board. */
  readonly cleared?: number;
  /** Row B has started waiting on the reader since the first board. */
  readonly bWaiting?: boolean;
  /** The Pi and OpenCode rows carry the server's "block state" gap, as before their adapter sends an event. */
  readonly blockGaps?: boolean;
}

export function sessionRows(options: FixtureOptions = {}): Record<string, unknown>[] {
  const rows: Record<string, unknown>[] = [
    {
      harness: 'claude',
      sid: SIDS.A,
      title: 'Combat Completion',
      project: 'projects/pendulum-of-despair',
      project_key: 'k-pod',
      state: 'needs_input',
      state_detail: 'Permission prompt: Bash',
      blocked_since: local(0, 11, 57),
      started_at: local(0, 9, 14),
      last_activity: local(0, 11, 57),
    },
    {
      harness: 'claude',
      sid: SIDS.B,
      title: 'Changelog for 2.4',
      project: 'recce/compass',
      project_key: 'k-rc',
      state: options.bWaiting ? 'needs_input' : options.bIdle ? 'idle' : 'working',
      active: !options.bIdle,
      state_detail: options.bWaiting
        ? 'Permission prompt: Edit'
        : options.bIdle
          ? 'awaiting your message'
          : 'running Bash',
      ...(options.bWaiting ? { blocked_since: local(0, 11, 59) } : {}),
      started_at: local(0, 10, 2),
      last_activity: local(0, 11, 59),
      first_prompt: 'write the release notes for 2.4',
      first_prompt_at: local(0, 10, 2),
      annotation_goal: 'Ship the 2.4 changelog',
      annotation_revision: 1,
    },
    {
      harness: 'codex',
      sid: SIDS.C,
      title: 'Parser cleanup',
      project: 'recce/compass',
      project_key: 'k-rc',
      worktree: 'parser-fix',
      state: 'working',
      state_detail: 'running tests',
      first_prompt_at: local(-1, 16, 2),
      last_activity: local(0, 11, 58),
    },
    {
      harness: 'claude',
      sid: SIDS.D,
      title: 'Session list paging',
      project: 'recce/compass',
      project_key: 'k-rc',
      state: 'idle',
      started_at: local(-1, 14, 30),
      last_activity: local(0, 10, 55),
      departures: [{ at: local(0, 10, 40), revision: 2 }],
      annotation_revision: 2,
    },
    {
      harness: 'claude',
      sid: SIDS.E,
      title: 'Theme tokens',
      project: 'recce/compass',
      project_key: 'k-rc',
      state: 'idle',
      ended_at: local(0, 10, 30),
      started_at: local(0, 8),
      last_activity: local(0, 10, 30),
    },
    {
      harness: 'gemini',
      sid: SIDS.F,
      title: 'Docs pass',
      project: 'compass',
      project_key: 'k-compass-a',
      state: 'idle',
      started_at: local(0, 7, 30),
      last_activity: local(0, 9),
    },
    {
      harness: 'cursor',
      sid: SIDS.G,
      title: 'Fix flaky test',
      project: 'recce/compass',
      project_key: 'k-rc',
      state: 'idle',
      last_activity: local(0, 8, 15),
    },
    {
      harness: 'pi',
      sid: SIDS.H,
      title: 'Notes',
      project: 'compass',
      project_key: 'k-compass-b',
      state: 'idle',
      last_activity: local(0, 7),
      ...(options.blockGaps ? { source_gaps: ['block state'] } : {}),
    },
    {
      harness: 'goose',
      sid: SIDS.I,
      title: 'Terraform plan',
      project: 'recce-cloud-infra',
      project_key: 'k-infra',
      state: 'idle',
      last_activity: local(0, 6, 20),
    },
    {
      harness: 'opencode',
      sid: SIDS.J,
      title: 'Scratch',
      project: '',
      state: '',
      last_activity: local(0, 5, 10),
      ...(options.blockGaps ? { source_gaps: ['block state'] } : {}),
    },
    {
      harness: 'codex',
      sid: SIDS.K,
      title: 'Cut the 2.4 release',
      project: 'recce/compass',
      project_key: 'k-rc',
      state: 'idle',
      started_at: local(0, 6, 45),
      last_activity: local(0, 7, 40),
      annotation_goal: 'Cut the 2.4 release',
      annotation_revision: 1,
      annotation_reading_count: 1,
      annotation_assessment: READING_K,
    },
    {
      harness: 'claude',
      sid: SIDS.L,
      title: 'Combat balance',
      project: 'projects/pendulum-of-despair',
      project_key: 'k-pod',
      state: 'idle',
      started_at: local(-1, 13),
      last_activity: local(-1, 13, 30),
    },
  ];
  if (options.showAll)
    rows.push(
      {
        harness: 'claude',
        sid: '6a7b8c9d0e1f',
        project: 'recce/compass',
        project_key: 'k-rc',
        state: 'idle',
        active: false,
        last_activity: local(-3, 10),
      },
      {
        harness: 'codex',
        sid: '7b8c9d0e1f2a',
        project: 'recce/compass',
        project_key: 'k-rc',
        state: 'idle',
        active: false,
        last_activity: local(-4, 10),
      },
      {
        harness: 'pi',
        sid: '8c9d0e1f2a3b',
        title: 'Old notes',
        project: 'compass',
        project_key: 'k-compass-b',
        state: 'idle',
        active: false,
        last_activity: local(-5, 10),
      },
    );
  return rows;
}

export function sessionsSearchPayload(options: FixtureOptions = {}): Record<string, unknown> {
  const annotate = options.annotate ?? true;
  return {
    generated: options.generated ?? GENERATED,
    window_hours: 24,
    ...(options.showAll ? { show_all: true } : {}),
    annotate,
    ...(options.unreadable
      ? { annotate_unreadable: 'The annotation store could not be read.' }
      : {}),
    annotate_cap: 240,
    annotate_goal_cap: 1000,
    ask: true,
    asks: [
      {
        id: 'q1',
        session_id: SIDS.A,
        harness: 'claude',
        project: 'projects/pendulum-of-despair',
        question: 'Run the combat suite now?',
        options: ['Yes, run it', 'Not yet'],
        age_sec: 180,
      },
    ],
    cleared: options.cleared ?? 0,
    harnesses: [...HARNESSES, ...OTHERS],
    sessions: sessionRows(options),
  };
}
