/* Literal outputs of reading.cutoff_text for a complete message tail: two selected entries with
   1,800/4,000 characters of the agent message, then one of four eligible checks fitting the prompt.
   Listing omissions remain a separate producer measurement; neither is a source-tail gap. */
const COVERAGE = {
  tail_truncated: false,
  tail_start: null,
  unlisted: 0,
  unread_checks: 0,
  goal_source: 'typed',
  other_commands: 0,
  read_only_commands: 0,
};

export const EXCERPTED_DRIFT = {
  cutoff:
    'Read all 2 entries after your intent: 1 message from the agent, 1 failed check. All are from within the last hour. 1 message was read only in part.',
  coverage: COVERAGE,
};

export const PROMPT_LIMITED_DRIFT = {
  cutoff:
    'Read 1 of the 4 entries after your intent: 1 failed check. It is from within the last hour. 2 passes or writes in the window were left unlisted; 3 checks had no room in the prompt.',
  coverage: { ...COVERAGE, unlisted: 2, unread_checks: 3 },
};
