import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { test } from 'node:test';

test('only the icon gateway and the drift proof can import react-icons', () => {
  const directory = mkdtempSync('frontend/s1-03-icon-probe-');
  try {
    for (const extension of ['ts', 'tsx', 'js', 'jsx', 'mts', 'mjs', 'cts', 'cjs']) {
      for (const source of ['react-icons', 'react-icons/pi']) {
        const path = `${directory}/import.${extension}`;
        writeFileSync(path, `export { PiMoonBold } from '${source}';\n`);
        const result = spawnSync('pnpm', ['exec', 'biome', 'lint', path], { encoding: 'utf8' });
        assert.match(
          result.stdout + result.stderr,
          /lint\/style\/noRestrictedImports/,
          `${extension}: ${source}`,
        );
        assert.equal(result.status, 1);
      }
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
  for (const path of ['frontend/src/ui/icons.tsx', 'frontend/stories/drift.checks.tsx']) {
    const result = spawnSync('pnpm', ['exec', 'biome', 'lint', path], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stdout + result.stderr);
  }
});
