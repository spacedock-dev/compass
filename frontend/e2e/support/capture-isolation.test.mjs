import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { chmod, cp, mkdir, mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { isAbsolute, join, relative, sep } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { copyProofPath } from './proof-copy.mjs';

const run = promisify(execFile);
const root = fileURLToPath(new URL('../../../', import.meta.url));
const fixture = fileURLToPath(new URL('./capture-browser.fixture.mjs', import.meta.url));
const firstViewFiles = [
  'session-first-view-after.json',
  ...[320, 375, 640, 1280].map((width) => `session-first-view-${width}.png`),
];
const driftFiles = [375, 1280].flatMap((width) =>
  [
    'result-and-an-open-correction',
    'a-running-analysis',
    'the-consent-step',
    'a-stale-result-and-a-gap',
  ].map((state) => `drift-${state}-${width}.png`),
);

async function snapshot(dir) {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  return Promise.all(
    entries
      .map((entry) => ({
        path: relative(dir, join(entry.parentPath, entry.name)),
        directory: entry.isDirectory(),
      }))
      .sort((left, right) => left.path.localeCompare(right.path))
      .map(async ({ path, directory }) => [
        path,
        directory ? null : await readFile(join(dir, path)),
      ]),
  );
}

test('each browser proof run leaves its own artifacts outside the checkout', async (t) => {
  const scratch = await mkdtemp(join(tmpdir(), 'compass-capture-isolation-'));
  const checkout = join(scratch, 'checkout');
  const temp = join(scratch, 'output');
  const paths = [];
  t.after(async () => {
    await Promise.all(paths.map(([path, directory]) => chmod(path, directory ? 0o700 : 0o600)));
    await rm(scratch, { recursive: true, force: true });
  });
  await mkdir(temp);
  await cp(join(root, 'frontend/e2e'), join(checkout, 'frontend/e2e'), {
    recursive: true,
    filter: copyProofPath,
  });
  await mkdir(join(checkout, 'frontend/test/golden/e2e'), { recursive: true });
  for (const path of ['recorded-name.ts', 'golden/e2e/drift-parity.json'])
    await cp(join(root, 'frontend/test', path), join(checkout, 'frontend/test', path));
  const before = await snapshot(checkout);
  for (const [path, contents] of before) paths.push([join(checkout, path), contents === null]);
  paths.push([checkout, true]);
  await Promise.all(paths.map(([path, directory]) => chmod(path, directory ? 0o500 : 0o400)));
  const results = [];
  for (const [proof, expectedFiles] of [
    ['session-first-view', firstViewFiles],
    ['drift-parity', driftFiles],
  ]) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const result = await run(
        process.execPath,
        ['--import', fixture, `frontend/e2e/${proof}.mjs`],
        {
          cwd: checkout,
          env: {
            ...process.env,
            TMPDIR: temp,
            TMP: temp,
            TEMP: temp,
            FIRST_VIEW_INVENTORY_ONLY: '',
            FIRST_VIEW_MUTATION: '',
            DRIFT_MUTATION: '',
            COMPASS_E2E_STEPS: 'no horizontal scroll, in every state',
            COMPASS_SCREENSHOTS: attempt === 0 ? '' : join(checkout, 'docs/screenshots'),
          },
          timeout: 15000,
        },
      ).catch((error) => error);
      results.push({ proof, expectedFiles, result });
    }
  }
  assert.deepEqual(await snapshot(checkout), before, 'the proof changed the checkout');
  const directories = new Set();
  for (const [index, { proof, expectedFiles, result }] of results.entries()) {
    await t.test(`${proof} invocation ${(index % 2) + 1}`, async () => {
      if (proof === 'session-first-view') {
        assert.equal(result.code, 1, result.stderr);
        assert.match(result.stderr, /Error: First-view captures completed/);
      } else {
        assert.equal(result.code, undefined, result.stderr);
      }
      const output = result.stderr.match(/^Browser proof artifacts in (.+)$/m)?.[1];
      assert.ok(output && isAbsolute(output), `${proof} must print its artifact directory`);
      const fromTemp = relative(temp, output);
      assert.ok(
        fromTemp && !isAbsolute(fromTemp) && !fromTemp.startsWith(`..${sep}`) && fromTemp !== '..',
      );
      assert.ok(!directories.has(output), `two runs share ${output}`);
      directories.add(output);
      assert.deepEqual((await readdir(output)).sort(), expectedFiles.toSorted());
      for (const file of expectedFiles)
        assert.ok((await readFile(join(output, file))).length, `${file} is empty`);
    });
  }
});
