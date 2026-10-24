// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseOutline } from './outline';

/* The outline as the real server recorded it (`frontend/test/fixtures/client-contract/`), parsed. */
const DIRECTORY = new URL('../../test/fixtures/client-contract/', import.meta.url);
const body = (name: string): unknown =>
  (
    JSON.parse(readFileSync(new URL(`${name}.json`, DIRECTORY), 'utf8')) as {
      response: { body: unknown };
    }
  ).response.body;

describe('parseOutline', () => {
  it('reads one block per person message from a recorded focused answer', () => {
    const outline = parseOutline(body('context-focused-prompts'));
    expect(outline?.state).toBe('ok');
    expect(outline?.blocks).toHaveLength(2);
    const [first] = outline?.blocks ?? [];
    expect(first?.prompt?.title).toBe('Add retry with backoff to the webhook handler.');
    expect(first?.span).toMatchObject({ entries: 2, first: 'fact:1b3f7a63986acb47' });
    expect(first?.counts).toMatchObject({ agentMessages: 1, checks: 0, files: 0 });
    expect(outline?.coverage).toMatchObject({
      startOffset: 0,
      agentReplies: 'read',
      checksAndFiles: 'read',
    });
  });

  it('reads an unavailable answer with its reason and no blocks', () => {
    const outline = parseOutline(body('context-focused-session'));
    expect(outline).toMatchObject({ state: 'unavailable', reason: 'unavailable', blocks: [] });
  });

  it('is no outline when the answer carries none or one not labelled as Compass grouping', () => {
    expect(parseOutline({ sources: { work: {} } })).toBeNull();
    expect(parseOutline(null)).toBeNull();
    const outline = { state: 'ok', made_by: 'model', basis: 'grouping', blocks: [] };
    expect(parseOutline({ sources: { outline } })).toBeNull();
    const unknown = { state: 'later', made_by: 'compass', basis: 'grouping', blocks: [] };
    expect(parseOutline({ sources: { outline: unknown } })).toBeNull();
  });

  it('keeps no block from a non-ok answer and drops a block with no span', () => {
    const block = { span: { first: 'a', last: 'b', entries: 2 }, counts: {} };
    const stale = { state: 'stale', made_by: 'compass', basis: 'grouping', blocks: [block] };
    expect(parseOutline({ sources: { outline: stale } })?.blocks).toEqual([]);
    const ok = {
      state: 'ok',
      made_by: 'compass',
      basis: 'grouping',
      blocks: [block, { prompt: null, counts: {} }],
      more_blocks: -1,
    };
    const parsed = parseOutline({ sources: { outline: ok } });
    expect(parsed?.blocks).toHaveLength(1);
    expect(parsed?.blocks[0]?.prompt).toBeNull();
    expect(parsed?.moreBlocks).toBe(0);
  });
});
