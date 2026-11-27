export const planLimits =
  'Compass cannot detect health information or confidential text typed into these sources.';

export const hostileDiagramBody =
  '<img src="https://diagram-canary.example.test/plan-image" onerror="window.planDiagramRan=true">' +
  '<script>window.planDiagramRan=true</script>' +
  '<a href="javascript:window.planDiagramRan=true">Run diagram</a>';

export const planBoard = {
  sessions: [
    {
      harness: 'codex',
      sid: 'shelf:review',
      project: 'Library pickup',
      title: 'Review the shelf layout',
      state: 'needs_input',
    },
    {
      harness: 'claude',
      sid: 'rota',
      project: 'Library pickup',
      title: 'Check the weekend rota',
      state: 'working',
    },
    // Waiting on you through the harness's own hook, with no ask sent through Compass.
    {
      harness: 'claude',
      sid: 'pytest',
      project: 'Library pickup',
      title: 'Run the shelf checks',
      state: 'needs_input',
      state_detail: 'Approve running the shelf checks',
    },
    {
      harness: 'claude',
      sid: 'labels',
      project: 'Library pickup',
      title: 'Print the shelf labels',
      state: 'needs_input',
    },
  ],
  harnesses: [
    { key: 'codex', label: 'Codex' },
    { key: 'claude', label: 'Claude Code' },
  ],
  ask: true,
  asks: [
    {
      harness: 'codex',
      session_id: 'shelf:review',
      question: 'Please confirm which shelves to keep clear.',
    },
  ],
};

/* What each waiting session says on Plan: the ask it sent, the request its harness published, or a plain
   sentence when neither was published. */
export const planWaiting = [
  [
    'Review the shelf layout',
    'Codex · Library pickup',
    'Please confirm which shelves to keep clear.',
  ],
  ['Run the shelf checks', 'Claude Code · Library pickup', 'Approve running the shelf checks'],
  [
    'Print the shelf labels',
    'Claude Code · Library pickup',
    'The agent is waiting for your input.',
  ],
] as const;

export const refusedPlanSettings = { state: 'refused', reason: 'malformed settings' } as const;
export const unconfiguredPlan = { state: 'not-configured' } as const;

export const readyPlan = {
  state: 'ready',
  goals: [
    {
      id: 'pickup',
      title: 'Make library pickup easier',
      doneWhen: 'Readers can collect a reserved book without joining the main queue.',
      lanes: ['shelf', 'weekends', 'signs', 'unpublished', 'shelf'],
      proposal: null,
    },
    {
      id: 'returns',
      title: 'Make after-hours returns easier',
      doneWhen: 'Readers can return books whenever the library is closed.',
      lanes: [],
      proposal: 'Proposed, not merged',
    },
  ],
  lanes: [
    {
      id: 'shelf',
      title: 'Set up the pickup shelf',
      doneWhen: null,
      date: null,
      state: null,
      sessions: ['session:["codex","shelf:review"]', 'session:["codex","missing"]'],
    },
    {
      id: 'weekends',
      title: 'Agree on weekend hours',
      doneWhen: null,
      date: null,
      state: null,
      sessions: null,
    },
    {
      id: 'signs',
      title: 'Put up signs at the entrance',
      doneWhen: null,
      date: null,
      state: null,
      sessions: [],
    },
  ],
  asks: [
    {
      id: 'hours',
      text: 'Should the pickup shelf stay open on Sundays?',
      at: '2026-11-26T13:15:00Z',
      timeLabel: 'from the log',
      source: 'Library plan log',
      lane: { id: 'shelf', title: 'Set up the pickup shelf' },
    },
    {
      id: 'untimed',
      text: 'Who can check the entrance signs?',
      at: null,
      timeLabel: null,
      source: 'Library plan log',
      lane: null,
    },
  ],
  design: [
    {
      title: 'Use the entrance alcove for pickups',
      summary: null,
      decided: true,
      source: 'Library design notes',
      date: { label: 'Changed', at: '2026-11-24' },
    },
  ],
  tracker: [
    {
      title: 'Print labels for the pickup shelf',
      group: 'done',
      source: 'Pickup tracker',
      date: null,
    },
    {
      title: 'Confirm the Saturday rota',
      group: 'Status not recognised',
      source: 'Pickup tracker',
      date: null,
    },
  ],
  inventory: [],
  diagrams: [
    {
      title: 'From the library entrance to the pickup shelf',
      caption: 'From the library entrance to the pickup shelf',
      kind: 'flowchart',
      source: 'Library diagrams',
      date: null,
      linkHosts: ['diagrams.example.org'],
      body: 'flowchart LR\nEntrance --> Shelf',
    },
  ],
  sources: [
    {
      label: 'Library goals',
      kind: 'goals',
      fileLabel: null,
      position: null,
      state: 'ok',
      reason: null,
    },
    {
      label: 'Annex design notes',
      kind: 'decisions',
      fileLabel: null,
      position: null,
      state: 'refused',
      reason: 'private',
    },
  ],
  logRejected: 0,
  limits: planLimits,
} as const;

type WireSource = {
  readonly label: string;
  readonly kind: string;
  readonly fileLabel: string | null;
  readonly position: number | null;
  readonly state: 'ok' | 'refused';
  readonly reason: string | null;
};

function wireSource(
  label: string,
  kind: string,
  { position = null, fileLabel = null, reason = null }: Partial<WireSource> = {},
): WireSource {
  return { label, kind, fileLabel, position, state: reason === null ? 'ok' : 'refused', reason };
}

const briefSlugs = ['deck', 'hull', 'keel', 'lamp', 'mast', 'paint', 'rigging', 'sails'] as const;

/* One repository with three inventory files (the second not committed, the third labelled in the
   settings), a draft branch that does not exist yet, and eight lane briefs, one of them refused. */
export const crowdedSources: readonly WireSource[] = [
  wireSource('Model ship', 'goals'),
  wireSource('Model ship', 'inventory', { position: 1 }),
  wireSource('Model ship', 'inventory', { position: 2, reason: 'not in branch' }),
  wireSource('Model ship', 'inventory', { position: 3, fileLabel: 'Spare parts' }),
  wireSource('Model ship', 'draft goals', { reason: 'branch missing' }),
  wireSource('Model ship', 'draft inventory', { position: 1, reason: 'branch missing' }),
  wireSource('Model ship', 'draft inventory', { position: 2, reason: 'branch missing' }),
  wireSource('Model ship', 'draft inventory', {
    position: 3,
    fileLabel: 'Spare parts',
    reason: 'branch missing',
  }),
  wireSource('Lane briefs', 'lane briefs'),
  ...briefSlugs.map((slug) =>
    wireSource(slug, 'lane brief', slug === 'mast' ? { reason: 'malformed' } : {}),
  ),
  wireSource('Coordination', 'event log'),
];

/* What each Sources row reads, in order, for crowdedSources. */
export const crowdedSourceRows = [
  'Model ship · goalsRead',
  'Model ship · inventory 1Read',
  'Model ship · inventory 2RefusedThe file is not on the branch.',
  'Model ship · Spare partsRead',
  'Model ship · draftRefusedThe branch is missing.',
  'Lane briefs7 read',
  'Lane brief · mastRefusedThe source did not have the expected format.',
  'CoordinationRead',
] as const;
