import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';
import { SUPPORTED_AGENTS } from './Help';

it('names exactly the collectors shipped with Compass', () => {
  const collectors = fileURLToPath(
    new URL('../../../compass/skills/compass/compass_runtime/collectors/', import.meta.url),
  );
  const keys = readdirSync(collectors)
    .filter((name) => name.endsWith('.py') && !name.startsWith('_'))
    .map((name) => name.slice(0, -3))
    .sort();
  expect(Object.keys(SUPPORTED_AGENTS).sort()).toEqual(keys);
  expect(Object.values(SUPPORTED_AGENTS).sort()).toEqual([
    'Antigravity CLI',
    'Claude Code',
    'Codex',
    'Cursor CLI',
    'Factory Droid',
    'Gemini CLI',
    'GitHub Copilot CLI',
    'Goose',
    'OpenCode',
    'Pi',
  ]);
});
