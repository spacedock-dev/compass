// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { mountProject } from '../project/testing';
import { createApiClient } from './client';

const recorded = (name: string) =>
  JSON.parse(readFileSync(`frontend/test/fixtures/client-contract/${name}.json`, 'utf8')).response
    .body;

it('a person reads the server’s shared absence words in the project view', async () => {
  const wire = recorded('data-terminal-project');
  const client = createApiClient({ fetch: async () => new Response(JSON.stringify(wire)) });
  const answer = await client.getData({ showAll: false, usage: false });
  expect(answer.kind).toBe('ok');
  if (answer.kind !== 'ok') throw new Error('board absent');
  const discard = (answer.body as unknown as Record<string, Record<string, string>>)[
    'annotate_discard'
  ];
  expect(discard?.['record']).toMatch(/^What you asked of this session was discarded/);
  const row = (answer.body.sessions as unknown as readonly Record<string, unknown>[])[0];
  expect(row?.['annotation_goal_why']).toBe('No goal typed for this session.');
  const page = mountProject({
    hash: '#n=project:terminal-project',
    data: wire,
    contexts: { 'key-terminal-project\n': recorded('context-terminal-project') },
  });
  await page.settle();
  expect(page.getByLabelText('Recovery summary').textContent).not.toContain('why:');
});
