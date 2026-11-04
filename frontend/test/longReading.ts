/* Current backend outcome shapes; no model or source execution in these UI proofs. */
export const LONG_INTERRUPTED_SENTENCE =
  'Compass stopped before this analysis outcome was saved. No new result is shown. Any recorded calls remain counted, and a fresh press is the only retry.';
export const PARTIAL_WHY =
  'Some agent messages could not fit the final comparison. This line cannot be judged from that partial comparison.';
export const EARLIER_READING = 'Earlier reading, saved before the interrupted analysis.';
const unknown = (clause: string) => ({
  result: 'not verifiable from available evidence',
  cites: [],
  detail: '',
  clause,
  why: 'long-reconciliation-coverage',
});
export const PARTIAL_READING = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'final',
  scope_text: 'Read to its final message.',
  ended_at_read: 1000,
  stamp: 'model · m',
  cutoff: 'Local findings from original evidence.',
  criteria: {
    goal: unknown('Ship the queue'),
    line_1: {
      result: 'departure',
      cites: ['c1'],
      detail: 'The retry check failed.',
      clause: 'Tests pass',
      why: 'failed-check-on-record',
    },
    claims: unknown('What the agent claimed'),
  },
};
