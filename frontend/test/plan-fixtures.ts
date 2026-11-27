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
  ],
  harnesses: [{ key: 'codex', label: 'Codex' }],
  ask: true,
  asks: [
    {
      harness: 'codex',
      session_id: 'shelf:review',
      question: 'Please confirm which shelves to keep clear.',
    },
  ],
};

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
    { label: 'Library goals', kind: 'goals', state: 'ok', reason: null },
    { label: 'Annex design notes', kind: 'decisions', state: 'refused', reason: 'private' },
  ],
  logRejected: 0,
  limits: planLimits,
} as const;
