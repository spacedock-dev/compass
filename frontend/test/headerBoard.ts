import { GENERATED } from './worthALookBoard';

export function headerBoard() {
  const scope = { project: 'acme/dashboard', harness: 'claude' };
  return {
    generated: GENERATED,
    ask: true,
    asks: [
      { id: 'permission', harness: 'claude', session_id: 'gate', question: 'Approve the command?' },
      { id: 'choice', harness: 'claude', session_id: 'request', question: 'Continue the import?' },
    ],
    sessions: [
      { ...scope, sid: 'active', title: 'Check the build', state: 'working', active: true },
      { ...scope, sid: 'working', title: 'Summarise the run', state: 'working' },
      {
        ...scope,
        sid: 'gate',
        title: 'Review permissions',
        state: 'needs_input',
        state_detail: 'Waiting for command approval',
      },
      { ...scope, sid: 'request', title: 'Import the records', state: 'working' },
      {
        ...scope,
        sid: 'dirty-end',
        title: 'Update requirements',
        ended_at: GENERATED - 100,
        dirty: true,
      },
      {
        ...scope,
        sid: 'clean-end',
        title: 'Refresh the fixtures',
        ended_at: GENERATED - 100,
        dirty: false,
      },
    ],
  };
}
