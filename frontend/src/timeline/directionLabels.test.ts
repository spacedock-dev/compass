import { describe, expect, it } from 'vitest';
import { buildRegistry, eventsForMode, readSemantic } from './semantic';

/* A direction on the timeline is the reader's words: the harness's paste tags, and the number inside them,
   never reach its label or the sentence drawn from it. */
const WRAPPED = '\n\n<pasted_content id="7">\nShip the queue behind a flag\n</pasted_content>\n';
const SESSION = { harness: 'claude', sid: 'a' };

describe('a direction on the timeline', () => {
  const raw = {
    facts: [
      {
        fact_id: 'dir',
        at: 100,
        type: 'user_message',
        summary: WRAPPED,
        work_item_id: 'w1',
        source_session: SESSION,
      },
      { fact_id: 'ask', at: 90, type: 'result', summary: 'Kept <pasted_content id="2"> as is' },
    ],
    work_items: [{ work_item_id: 'w1', label: 'ship-feature', kind: 'workflow_item' }],
    projections: {
      operator_intents: [{ projection_id: 'i1', derived_from: 'dir', at: 100, summary: WRAPPED }],
    },
  };

  it('is read without the paste tags, and an agent’s or a result’s words are left as they were', () => {
    const model = readSemantic(raw);
    expect(model.facts.find((fact) => fact.id === 'dir')?.summary).toBe(
      'Ship the queue behind a flag',
    );
    expect(model.intents[0]?.summary).toBe('Ship the queue behind a flag');
    expect(model.facts.find((fact) => fact.id === 'ask')?.summary).toBe(
      'Kept <pasted_content id="2"> as is',
    );
  });

  it('draws an event label with no tags and no entry number', () => {
    const model = readSemantic(raw);
    const registry = buildRegistry({
      model,
      delegations: [],
      focus: null,
      fallbackSession: 'claude:a',
    });
    const labels = eventsForMode(model, registry, 'all', null)
      .filter((event) => event.kind === 'direction')
      .map((event) => event.meaning);
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(label).toBe('Ship the queue behind a flag');
      expect(label).not.toMatch(/pasted_content|#\d/);
    }
  });
});
