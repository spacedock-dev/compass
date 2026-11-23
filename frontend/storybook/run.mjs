import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const mode = process.argv[2];
const commands = {
  dev: [
    'storybook/internal/bin/dispatcher',
    'dev',
    '--config-dir',
    'frontend/.storybook',
    '--host',
    '127.0.0.1',
    '--port',
    '6006',
    '--ci',
    '--no-open',
    '--no-version-updates',
  ],
  build: [
    'storybook/internal/bin/dispatcher',
    'build',
    '--config-dir',
    'frontend/.storybook',
    '--output-dir',
    '.storybook-build',
    '--disable-telemetry',
    '--test',
  ],
  test: [
    'vitest/vitest.mjs',
    'run',
    '--config',
    'frontend/.storybook/vitest.config.mts',
    '--project',
    'storybook',
    '--maxWorkers=1',
  ],
};
if (!Object.hasOwn(commands, mode)) throw new Error('Expected dev, build or test');
const [entry, ...args] = commands[mode];
/* One Chromium page ran every story file in turn, and on CI runners it ran out of memory late in
   the suite ("Browser connection was closed", three times on 2026-11-22 and 23, each after about
   two thirds of the files; docs/flaky-tests.md). Each shard is a separate Vitest run with a fresh
   browser, so no page carries the whole suite. */
const SHARDS = mode === 'test' ? 3 : 1;
const run = (extra) =>
  spawnSync(
    process.execPath,
    [
      fileURLToPath(
        mode === 'test'
          ? new URL('./vitest.mjs', import.meta.resolve('vitest/package.json'))
          : import.meta.resolve(entry),
      ),
      ...args,
      ...extra,
    ],
    {
      stdio: 'inherit',
      env: {
        ...process.env,
        STORYBOOK_DISABLE_TELEMETRY: '1',
        STORYBOOK_DISABLE_UPDATE_CHECK: '1',
      },
    },
  );
for (let shard = 1; shard <= SHARDS; shard += 1) {
  const result = run(SHARDS > 1 ? [`--shard=${shard}/${SHARDS}`] : []);
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
  if (process.exitCode !== 0) break;
}

if (mode === 'test' && process.exitCode === 0) {
  for (const args of [
    ['--test', 'frontend/storybook/browser.test.mjs'],
    ['frontend/storybook/offline.mjs'],
  ]) {
    const offline = spawnSync(process.execPath, args, { stdio: 'inherit' });
    if (offline.error) throw offline.error;
    process.exitCode = offline.status ?? 1;
    if (process.exitCode !== 0) break;
  }
}
