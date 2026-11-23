/* The design record's glossary is checked row for row in glossary.test.ts.
   The shown labels preserve the released board while each view adopts the ruled wording. */
type Columns = readonly [
  plain: string,
  replaces: string,
  technical: string,
  distinctFrom: string,
  exceptions: string,
];

interface GlossaryRow<Shown extends string | null> {
  readonly plain: string;
  readonly replaces: string;
  readonly technical: string;
  readonly distinctFrom: string;
  readonly exceptions: string;
  readonly status: 'ruled' | 'open';
  /** The existing board label. Null means there is no stand-alone label to carry forward. */
  readonly shown: Shown;
}

function ruled<Shown extends string | null>(
  [plain, replaces, technical, distinctFrom, exceptions]: Columns,
  shown: Shown,
): GlossaryRow<Shown> {
  return { plain, replaces, technical, distinctFrom, exceptions, status: 'ruled', shown };
}

function kept(columns: Columns): GlossaryRow<string> {
  return ruled(columns, columns[0]);
}

const how = (subject: string, verb: 'work' | 'works' = 'works'): string =>
  ['How', subject, verb].join(' ');

/* Only these labels are needed by the shipped shell. Keeping them separately exported lets the
   production build omit the decision metadata used by the parity test and the style guide. */
export const SHOWN = {
  compass: 'Compass',
  primary: 'Primary',
  breadcrumb: 'Breadcrumb',
  sessions: 'Sessions',
  projects: 'Projects',
  settings: 'Settings',
  session: 'Session',
  projectTabs: 'Project cockpit views',
  now: 'Now',
  course: 'Course',
  decisions: 'Decisions',
  console: 'Console',
  sessionDataNotPublished: 'Session data not published.',
  waitingForBoard: 'Waiting for the first board.',
  waitingTitle: '● Needs you ·',
  titleNotPublished: 'Title not published',
  commandOnlyTitle: 'No name: the session opened with a command',
  workingSessions: 'Working sessions',
  workingCountOne: '{count} session working',
  workingCountMany: '{count} sessions working',
  nothingWorking: 'Nothing working right now',
  attention: 'Needs you',
  intent: 'Goal history',
  showTechnicalDetails: 'Show technical details',
} as const;

export const SESSION_ROW_WORDS = {
  working: 'Working',
  waitingOnYou: 'Waiting on you',
  quiet: 'Quiet',
  ended: 'Ended',
  worthALook: 'Worth a look',
  slightlyOffCourse: 'Slightly off course',
  offCourse: 'Off course',
  wayOffCourse: 'Way off course',
  noGoalYet: 'No goal yet',
  notCheckedYet: 'Not checked yet',
  tooEarlyToTell: 'Too early to tell',
  cantTell: "Can't tell",
  goalTooVague: 'Goal too vague to check',
  outOfDate: 'Out of date',
} as const;

export const GOAL_LABEL = 'Goal';
export const ALLOWANCE_LABEL = 'Your AI allowance';
export const EXPLANATIONS = {
  goals: how('goals', 'work'),
  filterCounts: how('filter counts', 'work'),
  sessionHistory: how('session history'),
  aiAllowance: how('the AI allowance'),
} as const;

export const GLOSSARY = /* @__PURE__ */ (() =>
  ({
    // Shell and project tabs.
    compass: kept([
      SHOWN.compass,
      'Keeps current label',
      'Application name',
      'A project or session title',
      'The prefix or suffix in a document title',
    ]),
    primary: kept([
      SHOWN.primary,
      'Keeps current label',
      'Accessible name for the main navigation',
      'Project tabs',
      'Accessible navigation label',
    ]),
    breadcrumb: kept([
      SHOWN.breadcrumb,
      'Keeps current label',
      'Accessible name for the parent links',
      'Primary navigation',
      'Accessible navigation label',
    ]),
    sessions: kept([
      SHOWN.sessions,
      'Keeps current label',
      'Session list and filters',
      'A single Session page',
      'The sessions slug stays',
    ]),
    projects: kept([
      SHOWN.projects,
      'Keeps current label',
      'Projects list and grouping evidence',
      'A single Project page',
      'The projects slug stays',
    ]),
    settings: kept([
      SHOWN.settings,
      'Keeps current label',
      'Saved choices and their owners',
      "A session's own controls",
      'The settings slug stays',
    ]),
    session: kept([
      SHOWN.session,
      'Keeps current label',
      'Session identity',
      'A reported session title',
      'Crumb when the session cannot be found. The document title may use its ID',
    ]),
    projectTabs: kept([
      SHOWN.projectTabs,
      'Keeps current label',
      'Accessible group name for the project tab strip',
      'Primary navigation',
      'Accessible tab list label',
    ]),
    now: kept([
      SHOWN.now,
      'Keeps current label',
      "The project's current evidence",
      'Session activity on the board',
      'Default project tab',
    ]),
    course: kept([
      SHOWN.course,
      'Keeps current label',
      'Observed direction changes',
      'A progress level',
      'The course tab slug stays',
    ]),
    decisions: kept([
      SHOWN.decisions,
      'Keeps current label',
      'Recorded project decisions',
      'Current state',
      'The decisions tab slug stays',
    ]),
    console: kept([
      SHOWN.console,
      'Keeps current label',
      'Read-only terminal',
      'A place to send a command',
      'The console tab slug stays. The terminal moves to technical details',
    ]),
    sessionDataNotPublished: kept([
      SHOWN.sessionDataNotPublished,
      'Keeps current label',
      'The session collection is missing',
      'A measured zero',
      'Used after a board arrives without session data',
    ]),
    waitingForBoard: kept([
      SHOWN.waitingForBoard,
      'Keeps current label',
      'Initial board read',
      'A measured zero',
      'Used before the first board arrives',
    ]),
    waitingTitle: kept([
      SHOWN.waitingTitle,
      'Keeps current label',
      'Published request or block on the open session',
      'The Needs you navigation destination',
      'Browser tab title prefix',
    ]),
    titleNotPublished: kept([
      SHOWN.titleNotPublished,
      'Keeps current label',
      'Missing or identifier-only session title',
      'A session ID or a command-only opening',
      'Session heading, breadcrumb and browser tab title',
    ]),
    commandOnlyTitle: kept([
      SHOWN.commandOnlyTitle,
      'Keeps current label',
      'The opening prompt was a harness command',
      'A missing published title',
      'Session heading, breadcrumb and browser tab title',
    ]),
    workingSessions: kept([
      SHOWN.workingSessions,
      'Names the pill for assistive technology',
      'Displayed Working state',
      'The event-backed running count',
      'Header status',
    ]),
    workingCountOne: kept([
      SHOWN.workingCountOne,
      'Singular Working count',
      'One session displays Working',
      'Observed subagents',
      'Header pill',
    ]),
    workingCountMany: kept([
      SHOWN.workingCountMany,
      'Plural Working count',
      'More than one session displays Working',
      'Observed subagents',
      'Header pill',
    ]),

    // Recorded language decisions.
    goal: ruled(
      [
        GOAL_LABEL,
        'Intent, Intent and drift',
        'Saved intent, source, revision and lines read',
        "An agent's task or a provisional prompt",
        'The `intent` slug and technical names keep their spelling',
      ],
      GOAL_LABEL,
    ),
    doneLooksLike: ruled(
      [
        'What "done" looks like',
        'Expected outcome (optional)',
        'An outcome line and its evidence',
        'The goal itself or proof of completion',
        'Technical fields retain their names',
      ],
      'Expected outcome (optional)',
    ),
    intent: ruled(
      [
        SHOWN.intent,
        'Intent log',
        'Saved goal revisions and source',
        "A session's current progress",
        'The `#n=intent` fragment survives',
      ],
      SHOWN.intent,
    ),
    checkProgress: ruled(
      [
        'Check progress',
        'Analyze drift',
        'Drift, read scope and result',
        'Live monitor, tests and builds',
        'Existing CLI flags and skill actions',
      ],
      'Analyze drift',
    ),
    checkProgressAgain: ruled(
      [
        'Check progress again',
        'Analyze again, Check again',
        'Prior reading and its recency',
        'The first check or an Out of date state',
        'Same label for a current or stale prior reading',
      ],
      'Analyze again',
    ),
    progressCheck: ruled(
      [
        'Progress check',
        'Drift check',
        'The reading and evidence',
        'Tests and builds run by the agent',
        'Terminal flag `--drift`',
      ],
      'Drift level',
    ),
    readingLooksWrong: ruled(
      [
        'This reading looks wrong',
        'Mark as inaccurate',
        'The marked reading and what the mark changed',
        'Editing the goal',
        'Undo is still offered',
      ],
      'Mark as inaccurate',
    ),
    updateGoalInstead: ruled(
      [
        'Update my goal instead',
        'Update intent instead',
        'The goal revision',
        'Marking the reading wrong',
        'Opens Goal in edit mode',
      ],
      'Update intent instead',
    ),
    dismiss: ruled(
      [
        'Dismiss',
        'No standalone attention-row control',
        'Server dismissal record',
        'Mark as read',
        'Survives Forget',
      ],
      null,
    ),
    markAsRead: ruled(
      [
        'Mark as read',
        'No standalone control',
        'Server dismissal record',
        'Dismiss',
        'Survives Forget',
      ],
      null,
    ),
    steerBack: kept([
      'Steer back',
      'Keeps current label',
      'Editable correction and its evidence',
      'Editing the goal',
      'Compass never sends the correction',
    ]),
    useYourPrompt: kept([
      'Use your prompt',
      'Keeps current label',
      'Saved prompts in this session',
      'Editing the goal directly',
      'Stays visible in read mode',
    ]),
    editGoal: ruled(
      [
        'Edit goal',
        'Direct editing in the goal field',
        'Goal draft and revision',
        'Adopting a saved prompt',
        'Beside Use your prompt',
      ],
      null,
    ),
    yourData: ruled(
      [
        'Your data',
        'No dedicated Settings section',
        'Data kept and settings reset by Forget',
        'AI use settings',
        'The Forget explanation opens here in Settings',
      ],
      null,
    ),
    whereOffCourse: ruled(
      [
        'Where it went off course',
        'Departure · Goal',
        'Departure, supporting evidence and citations',
        'A warning signal or a proposed correction',
        'Data token `departure` stays',
      ],
      'Departure · Goal',
    ),
    helpers: ruled(
      [
        'Helpers',
        'Subagents',
        'Recorded subagent activity',
        'Declared child sessions',
        'Technical language may say subagents',
      ],
      'Subagents',
    ),
    agent: ruled(
      [
        'Agent',
        'Harness',
        'Harness identity',
        'A particular session',
        'Technical language may say harness',
      ],
      'Harness',
    ),
    attention: ruled(
      [
        SHOWN.attention,
        'Attention',
        'Published request, gate and evidence',
        'Waiting on you, the state and section',
        '`attention` slug and `n` shortcut',
      ],
      SHOWN.attention,
    ),
    working: kept([
      SESSION_ROW_WORDS.working,
      'WORKING',
      'The source-backed working state',
      'Right now membership',
      'Working now is the card label',
    ]),
    waitingOnYou: kept([
      SESSION_ROW_WORDS.waitingOnYou,
      'Needs input, Needs you now',
      'The exact request or gate',
      'Needs you, the navigation destination',
      'Gate detail appears on the session page and in Needs you',
    ]),
    quiet: kept([
      SESSION_ROW_WORDS.quiet,
      'Idle',
      'The observed turn-end state',
      'Ended or a scan-only absence',
      'Projects uses No recent activity',
    ]),
    ended: kept([
      SESSION_ROW_WORDS.ended,
      'Finished, Finished cleanly',
      'End evidence and any observed outcome',
      'A turn end or proof of success',
      'Ready to wrap up requires a clean end',
    ]),
    worthALook: ruled(
      [
        SESSION_ROW_WORDS.worthALook,
        'At risk',
        'The underlying warning or end evidence',
        'A session state or progress level',
        'Shows as a flag on a state',
      ],
      'At risk',
    ),
    readyToWrapUp: ruled(
      [
        'Ready to wrap up',
        'Close the loop',
        'The observed end and outcome',
        'Worth a look',
        'Needs you badge excludes this section',
      ],
      'Close the loop',
    ),
    onTrack: ruled(
      [
        'On track',
        'None or low',
        '`none_or_low`',
        "Proof of completion or Can't tell",
        'Session card and header, with meter and Help explaining it',
      ],
      'None or low',
    ),
    slightlyOffCourse: ruled(
      [
        SESSION_ROW_WORDS.slightlyOffCourse,
        'Medium',
        '`medium`',
        'Off course or a live estimate on a row',
        'Row pill requires a stored departure',
      ],
      'Medium',
    ),
    offCourse: ruled(
      [
        SESSION_ROW_WORDS.offCourse,
        'High',
        '`high`',
        'A generic risk signal',
        'Row pill requires a stored departure',
      ],
      'High',
    ),
    wayOffCourse: ruled(
      [
        SESSION_ROW_WORDS.wayOffCourse,
        'Extreme',
        '`extreme`',
        'A dirty end',
        'Row pill requires a stored departure',
      ],
      'Extreme',
    ),
    noGoalYet: kept([
      SESSION_ROW_WORDS.noGoalYet,
      'Generic Not checked',
      'Goal availability',
      'Not checked yet',
      'Also a Progress check filter chip',
    ]),
    notCheckedYet: kept([
      SESSION_ROW_WORDS.notCheckedYet,
      'Generic Not checked',
      'No check recorded',
      'No goal yet or Out of date',
      'Plain text',
    ]),
    tooEarlyToTell: ruled(
      [
        SESSION_ROW_WORDS.tooEarlyToTell,
        'Not enough recorded yet',
        '`not_enough` and the evidence floor',
        "Can't tell",
        'Plain text',
      ],
      'Not enough recorded yet',
    ),
    cantTell: ruled(
      [
        SESSION_ROW_WORDS.cantTell,
        'Goal-only reading with no level',
        'Missing proof that the goal was met',
        'On track',
        'Plain text',
      ],
      null,
    ),
    goalTooVague: ruled(
      [
        SESSION_ROW_WORDS.goalTooVague,
        'Goal too vague to analyze against',
        'Reading refusal and reason',
        'Too early to tell',
        'Plain text',
      ],
      'No level: the goal is too vague to analyze against.',
    ),
    outOfDate: ruled(
      [
        SESSION_ROW_WORDS.outOfDate,
        'Stale or withdrawn reading',
        'Why the prior reading is stale or withdrawn',
        'Never checked',
        'Rerun still reads Check progress again',
      ],
      null,
    ),
    pauseAi: ruled(
      [
        'Pause all AI use',
        'Pause model calls',
        'Shared server pause state',
        'The Summaries switch or Live monitor',
        '`--pause-model-calls` and skill action `pause`',
      ],
      'Pause model calls',
    ),
    resumeAi: ruled(
      [
        'Resume AI use',
        'Resume model calls',
        'Shared server pause state',
        'Starting a check, summary or monitor',
        'Existing terminal flags',
      ],
      'Resume model calls',
    ),
    liveMonitor: kept([
      'Live monitor',
      'Live monitor (kept)',
      'Live monitor · Haiku, scope and cadence',
      'A reader-requested check',
      "Session's technical layer. Settings points there",
    ]),
    aiAllowance: ruled(
      [
        ALLOWANCE_LABEL,
        'Capacity',
        'Provider plan quota and measurement',
        'Daily progress-check cap or prompt size limit',
        'Allowance refers only to this plan quota',
      ],
      ALLOWANCE_LABEL,
    ),
    progressCheckReadSize: ruled(
      [
        'How much a progress check reads',
        'Estimated prompt allowances',
        'Prompt size limits and exact bytes',
        'Your AI allowance',
        'Behind Customize. Slider labels name what they cap in KB',
      ],
      'Estimated prompt allowances',
    ),
    usesAi: ruled(
      [
        'Uses AI',
        'Cost implied by Analyze',
        'The destination, what is sent and its limits',
        'Number of remaining checks',
        'Always beside Check progress',
      ],
      null,
    ),
    dailyChecksLeft: ruled(
      [
        'N of 100 daily checks left',
        'Budget count',
        'Rolling cap and when capacity returns',
        'Plan quota',
        'Show at 10 or fewer checks left',
      ],
      null,
    ),
    howGoalsWork: ruled(
      [
        EXPLANATIONS.goals,
        'How Intent and drift works',
        'Goal sources, adoption and revisions',
        'A separate Help-only explainer',
        'Open in place from Goal. Help links there',
      ],
      EXPLANATIONS.goals,
    ),
    howFilterCountsWork: ruled(
      [
        EXPLANATIONS.filterCounts,
        'How these counts work',
        'Filter option counts and board-wide counts',
        'The count of rows shown',
        'Opens beneath the filters',
      ],
      EXPLANATIONS.filterCounts,
    ),
    howSessionHistoryWorks: ruled(
      [
        EXPLANATIONS.sessionHistory,
        'What recent means',
        'The published window and what recently observed means',
        'Whether a harness process is still open',
        'Opens above the earlier rows',
      ],
      EXPLANATIONS.sessionHistory,
    ),
    howProgressChecksWork: ruled(
      [
        how('progress checks', 'work'),
        'Drift explainer',
        'What the reading can and cannot establish',
        'A verdict or account of completed work',
        'Keep the local explanation next to the reading',
      ],
      null,
    ),
    howProjectGroupingWorks: ruled(
      [
        how('project grouping'),
        'Project grouping explanation',
        'Project evidence and folder identity',
        'Session state or agent type',
        'Explains Unnamed folder',
      ],
      null,
    ),
    howAiAllowanceWorks: ruled(
      [
        EXPLANATIONS.aiAllowance,
        'Quota explainer',
        'Provider reading, pace and measurement limits',
        'How much a progress check reads',
        'Help and the plan quota card use the same subject',
      ],
      EXPLANATIONS.aiAllowance,
    ),

    // Section and disclosure labels.
    help: ruled(
      [
        'Help',
        'New destination',
        'Links to the canonical explanations',
        'A second Goal explainer',
        'Help ships in a later slice',
      ],
      null,
    ),
    project: kept([
      'Project',
      'Keeps current label',
      'Project identity',
      'The Projects destination',
      'Project names come from the board',
    ]),
    workingNow: ruled(
      [
        'Working now',
        'Active now',
        'Count of sessions in the Working state',
        'Sessions in the Right now group',
        'Uses the same Working count as the header',
      ],
      'Active now',
    ),
    nothingWorking: ruled(
      [
        SHOWN.nothingWorking,
        'Running count at zero',
        'Measured Working count of zero',
        'No published board',
        'Header only after the board is read',
      ],
      SHOWN.nothingWorking,
    ),
    whatCompassCantSee: ruled(
      [
        "What Compass can't see",
        'Also at risk, off the session count',
        'Board-level coverage limits',
        'A session count',
        'Stays visible on the first layer',
      ],
      'Also at risk, off the session count',
    ),
    isItOnTrack: ruled(
      [
        'Is it on track?',
        'Drift',
        'Reading evidence and scope',
        'Whether work is complete',
        'Session progress card',
      ],
      'Drift',
    ),
    rightNow: ruled(
      [
        'Right now',
        'Active now',
        'Published current work and coming-next signals',
        'Count of sessions in the Working state',
        'On Sessions the earlier group names its time window',
      ],
      'Active now',
    ),
    whatsHappened: ruled(
      [
        "What's happened so far",
        'Session activity and summary areas',
        'Session history and sources',
        'A goal verdict',
        'Session page section',
      ],
      null,
    ),
    atAGlance: ruled(
      [
        'At a glance',
        'Session facts spread across the page',
        'Published session facts',
        'What the session intends to do',
        'Section title on the Session page',
      ],
      null,
    ),
    all: ruled(
      [
        'All',
        'Unfiltered Sessions list',
        'Published Sessions population',
        'Working sessions alone',
        'First Sessions tab',
      ],
      null,
    ),
    activeToday: ruled(
      [
        'Active today',
        'Active',
        'Evidence of recent project activity',
        "A session's Working state",
        'Projects group',
      ],
      'Active',
    ),
    noRecentActivity: ruled(
      [
        'No recent activity',
        'Recently observed',
        'Published project activity history',
        'The Quiet session state',
        'Projects group',
      ],
      'Recently observed',
    ),
    stateNotPublished: kept([
      'State not published',
      'Keeps current label',
      'The missing state field',
      'The Quiet session state',
      'Text only',
    ]),
    waitingOnChild: kept([
      'Waiting on child',
      'Keeps current label',
      'The reported child and relationship',
      'Waiting on you',
      'Text only',
    ]),
    readByScanning: kept([
      'Read by scanning: no turn end can be observed here',
      'Keeps current label',
      'Collector scope',
      'The Quiet session state',
      'Text only',
    ]),
    showTechnicalDetails: ruled(
      [
        SHOWN.showTechnicalDetails,
        'Separate technical controls',
        'Activity log, AI use, limits and raw evidence',
        "What Compass can't see",
        'Opens in place on the surfaces with technical evidence',
      ],
      SHOWN.showTechnicalDetails,
    ),
    aiUse: ruled(
      [
        'AI use',
        'Separate model and quota controls',
        'Model and quota settings',
        'The AI allowance',
        'Names the Settings section',
      ],
      null,
    ),
    aiUseAndPrivacy: ruled(
      [
        'AI use and privacy',
        'Separate model controls and disclosures',
        'Model settings and what is sent',
        'The AI allowance',
        'Names the Session technical tab',
      ],
      null,
    ),
    customize: ruled(
      [
        'Customize',
        'Always-visible prompt limits',
        'Prompt size controls',
        'Your AI allowance',
        'Opens How much a progress check reads',
      ],
      null,
    ),
  }) as const)();
