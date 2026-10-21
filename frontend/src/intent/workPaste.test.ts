import { describe, expect, it } from 'vitest';
import { workEntries } from './work';

/* Claude Code wraps a paste in `<pasted_content id="N">` tags, and a server or a history older than the
   strip still publishes a message's title with them. Every surface reads its words from one entry list, so the
   tags come off where the list is made: the direction select's title, the evidence quote and the work list
   cannot draw them (stories hold each surface). */
const SESSION = { harness: 'claude', sid: 's1' };
const fact = (id: string, type: string, summary: string) => ({
  fact_id: id,
  type,
  by: type === 'user_message' ? 'person:me' : 'agent',
  at: 100,
  summary,
  source_session: SESSION,
});
const entries = (...facts: ReturnType<typeof fact>[]) =>
  workEntries({ harness: 'claude', sid: 's1' }, { facts });

describe('the words of a message in the entry list', () => {
  it("carry no paste tag, and keep the reader's own words around it", () => {
    const [entry] = entries(
      fact('u1', 'user_message', 'Also, <pasted_content id="3">Back to my goal: ship it.'),
    );
    expect(entry?.summary).toBe('Also, Back to my goal: ship it.');
  });

  it('are the tag-free words when the whole title was a wrapper opening', () => {
    const [entry] = entries(
      fact('u1', 'user_message', '<pasted_content id="3"> Back to my goal: Ship the queue'),
    );
    expect(entry?.summary).toBe('Back to my goal: Ship the queue');
  });

  it('say nothing was published when only a tag was', () => {
    const [entry] = entries(fact('u1', 'user_message', '<pasted_content id="3">'));
    expect(entry?.summary).toBe('No summary published');
  });

  it("leave an agent's words alone: a tag it wrote about is its own text", () => {
    const [entry] = entries(
      fact('a1', 'agent_message', 'The `<pasted_content id="3">` tag is stripped.'),
    );
    expect(entry?.summary).toBe('The `<pasted_content id="3">` tag is stripped.');
  });
});
