import { expect, it } from 'vitest';
import { intentDraft, promptCandidate } from './intent';
import { goalCell, sessionsContext } from './rows';

it('a recognised Codex latest prompt is neither a draft nor a row goal', () => {
  const context = sessionsContext({ annotate: true });
  const session = {
    harness: 'codex',
    title: 'Back to my goal: Ship the queue',
    prompt_at: 170.05,
    prompt_states_work: true,
    copied_prompts: [{ fact_id: 'fact:0000000000000001', at: 170, quoted_as: ['title'] }],
  };
  expect(promptCandidate(session, 'latest-prompt')).toBeNull();
  expect(intentDraft(session, context)).toBeNull();
  expect(goalCell(session, context).text).toBe('No goal yet');

  const own = {
    ...session,
    title: 'Keep working on the parser tests.',
    copied_prompts: [{ ...session.copied_prompts[0], quoted_as: [] }],
  };
  expect(promptCandidate(own, 'latest-prompt')).toMatchObject({ text: own.title, at: 170.05 });
  expect(intentDraft(own, context)).toMatchObject({ text: own.title });
  expect(goalCell(own, context).text).toBe(own.title);
});
