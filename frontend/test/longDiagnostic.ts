import { LONG_PLAN } from './longPlan';
import { longWithheld } from './fixtures/vocabulary.json';

export const LONG_INCOMPLETE_SENTENCE = longWithheld['long-incomplete'];
export const LATEST_OLDER = 'Earlier reading, saved before the latest long analysis.';
export const LONG_DIAGNOSTIC = {
  version: 1,
  kind: 'long-analysis',
  plan: LONG_PLAN.plan,
  source: null,
  maps: null,
  observations: null,
  accounting: {
    state: 'minimum',
    totals: { calls: 4, prompt_bytes: 24000, reply_bytes: 4 * LONG_PLAN.plan.limits.reply_bytes },
    attempted_job: 1,
  },
  outcome: 'withheld',
  complete: false,
  binding: {
    revision: 3,
    revision_at: 990,
    window_start: 100,
    window_end: 1000,
    scope: 'final',
    end_kind: 'session-end',
    open_call_at: null,
    job_started_at: 1001,
  },
};
