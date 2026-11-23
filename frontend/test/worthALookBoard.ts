export const GENERATED = 1_900_000_000;

export function worthALookBoard() {
  const ended = { state: 'idle', ended_at: GENERATED - 100 };
  const quiet = { state: 'idle', finished_at: GENERATED - 120 };
  const location = { project: 'shared', project_identity_source: 'working directory path' };
  const departure = {
    annotation_goal: 'Finish the release work',
    annotation_revision: 1,
    annotation_assessment: {
      revision_read: 1,
      scope: 'last-turn',
      criteria: {
        goal: { result: 'departure', cites: ['fact:check'], clause: 'Finish the release work' },
      },
    },
  };
  const evidence = {
    gate: { state: 'needs_input', state_detail: 'Waiting for you to approve a command' },
    request: { state: 'working' },
    'dirty-end': { ...ended, dirty: true, changed: 2 },
    'dirty-unknown-count': { ...ended, dirty: true, changed: -1 },
    'dirty-one-entry': { ...ended, dirty: true, changed: 1 },
    'clean-end': { ...ended, dirty: false },
    'unknown-end': ended,
    'dirty-stop': { ...quiet, dirty: true, changed: 2 },
    loop: { state: 'working', loop: { errors: 3 }, turn: { long: true } },
    'long-turn': { state: 'working', turn: { long: true } },
    'quiet-launch': {
      ...quiet,
      delegated_launches: 1,
      delegated_unpaired: 1,
      delegated_latest_launch_at: GENERATED - 2600,
      delegated_last_activity_at: GENERATED - 2500,
      delegated_quiet_since: GENERATED - 2400,
      delegated_visibility: 'partial',
    },
    disagreement: { ...quiet, active: true },
    'shared-one': { ...quiet, ...location, project_key: 'path:one' },
    'shared-two': { ...quiet, ...location, project_key: 'path:two' },
    'drift-none': {
      ...quiet,
      ...departure,
      annotation_assessment: {
        ...departure.annotation_assessment,
        criteria: { goal: { result: 'on_track', cites: ['fact:check'] } },
      },
      stored_progress: 'on_track',
    },
    'drift-low': { ...quiet, ...departure, stored_progress: 'low' },
    'drift-medium': { ...quiet, ...departure, stored_progress: 'medium' },
    'drift-high': { ...quiet, ...departure, stored_progress: 'high' },
  };
  return {
    generated: GENERATED,
    ask: true,
    annotate: true,
    asks: [
      { id: 'gate-ask', harness: 'claude', session_id: 'gate', question: 'Approve?' },
      { id: 'exact-ask', harness: 'claude', session_id: 'request', question: 'Continue?' },
    ],
    harnesses: [
      { key: 'claude', label: 'Claude Code', discovered: true, reports_needs_input: true },
    ],
    usage: [{ harness: 'claude', state: 'ok', fiveH: { pct: 89 } }],
    sessions: Object.entries(evidence).map(([sid, fields]) => ({
      sid,
      title: sid,
      project: sid,
      harness: 'claude',
      last_activity: GENERATED - 100,
      ...fields,
    })),
  };
}
