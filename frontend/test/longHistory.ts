export const HISTORY_ITEM = {
  job_id: 'a'.repeat(32),
  state: 'interrupted',
  started_at: 1000,
  updated_at: 1100,
  terminal_at: 1100,
  unsettled: false,
  accounting: 'exact',
  exact: { calls: 4, prompt_bytes: 10000, reply_bytes: 2000 },
  minimum: { calls: 4, prompt_bytes: 10000, reply_bytes: 2000 },
  reason: '',
};
export const LONG_HISTORY = { version: 1, items: [HISTORY_ITEM], incomplete: false, reason: '' };
