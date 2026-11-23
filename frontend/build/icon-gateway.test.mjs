import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const biome = fileURLToPath(import.meta.resolve('@biomejs/biome/bin/biome'));

function lint(path, cwd) {
  // The script-denied pnpm install leaves a shebang-less shim that macOS cannot spawn directly.
  const result = spawnSync(process.execPath, [biome, 'lint', path], { cwd, encoding: 'utf8' });
  if (result.error) throw result.error;
  return { status: result.status, output: result.stdout + result.stderr };
}

test('only the icon gateway and the drift proof can import react-icons', () => {
  // The probes live outside the repository, beside a copy of its Biome config. A probe folder
  // inside frontend/ raced package.test.mjs, which copies frontend/ while this test deletes it,
  // and failed a merge-queue run with ENOENT (docs/flaky-tests.md).
  const directory = mkdtempSync(join(tmpdir(), 'compass-icon-probe-'));
  try {
    copyFileSync('biome.json', join(directory, 'biome.json'));
    mkdirSync(join(directory, 'frontend/src/probe'), { recursive: true });
    for (const extension of ['ts', 'tsx', 'js', 'jsx', 'mts', 'mjs', 'cts', 'cjs']) {
      for (const source of ['react-icons', 'react-icons/pi']) {
        const path = `frontend/src/probe/import.${extension}`;
        writeFileSync(join(directory, path), `export { PiMoonBold } from '${source}';\n`);
        const result = lint(path, directory);
        assert.match(
          result.output,
          /lint\/style\/noRestrictedImports/,
          `${extension}: ${source}\n${result.output}`,
        );
        assert.equal(result.status, 1);
      }
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
  for (const path of ['frontend/src/ui/icons.tsx', 'frontend/stories/drift.checks.tsx']) {
    const result = lint(path);
    assert.equal(result.status, 0, result.output);
  }
});
