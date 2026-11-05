import { LONG_PLAN } from './longPlan';

/** Native long Job metadata: caps are the job's frozen plan, never UI defaults. */
export const LONG_JOB = {
  id: 'long-j1',
  phase: 'collect',
  steps: [
    { phase: 'collect', text: 'Collecting the record' },
    { phase: 'read', text: 'Reading it' },
    { phase: 'write', text: 'Writing the result' },
  ],
  mode: 'long',
  plan: LONG_PLAN.plan,
  progress: {
    version: 1,
    stage: 'source',
    source: { streams_total: null, streams_verified: null, bytes_read: null, pages_read: null },
    evidence: { planned: null, ended: 0, current: null },
    reconciliation: { ordinal: LONG_PLAN.plan.max_calls, state: 'not-started' },
    accounting: { state: 'unknown', totals: null },
  },
};

export const EVIDENCE_PROGRESS = {
  ...LONG_JOB.progress,
  stage: 'evidence',
  source: { streams_total: 2, streams_verified: 2, bytes_read: 12000, pages_read: 6 },
  evidence: { planned: 7, ended: 3, current: 4 },
  accounting: {
    state: 'exact',
    totals: { calls: 4, prompt_bytes: 24000, reply_bytes: 4 * LONG_PLAN.plan.limits.reply_bytes },
  },
};
