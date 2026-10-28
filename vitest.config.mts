import { availableParallelism } from 'node:os';
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/* Every legacy answer the goldens hold was formatted in one zone, so the zone is fixed rather than the desk's:
   a clock word or a day-qualified date read in another zone is a different string. Set here, before any worker
   starts, because a worker thread cannot change the process zone after it has begun. The locale is fixed for
   the same reason: the port and the legacy page both format with the default locale, and the goldens hold the
   en-US strings (measured: under de_DE a daily-limit sentence reads "15.1.2027, 08:00:00" against the
   recorded "1/15/2027, 8:00:00 AM"). */
process.env['TZ'] = 'UTC';
process.env['LC_ALL'] = 'en_US.UTF-8';
process.env['LANG'] = 'en_US.UTF-8';
process.env['LANGUAGE'] = 'en_US';

/* Vitest's own default (one worker per core but one), floored at two for the VM pool below; see there. */
const WORKERS = Math.max(2, availableParallelism() - 1);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./frontend/src', import.meta.url)) } },
  test: {
    setupFiles: ['frontend/test/setup.ts'],
    /* Two projects by file kind. A `.tsx` test renders React and needs jsdom; a `.ts` test is logic, and building
       a jsdom window for each of those files was about a third of the suite's environment time (measured
       2026-10-28: 92 of the 108 `.ts` files pass unchanged under Node). A `.ts` file that does need a DOM says so
       with an `@vitest-environment jsdom` comment, and one that forgets fails on a missing `document` rather than
       passing. `include` lives on each project because a project's arrays are appended to the root's.

       The jsdom project runs in VM contexts inside long-lived workers. Each file gets a fresh VM context, jsdom
       window and module graph; what the worker keeps is the jsdom package and the source files' bytes, which a
       fork per file used to load again each time. The whole suite went from 101 to 63 seconds on two workers
       (measured 2026-10-28). The logic project stays on plain forks, because a VM context gives it a second
       realm: `toBeInstanceOf(Array)` failed on an array built in the test, and Vite's native bundler refused
       plugin objects made inside the context.

       A VM pool never isolates, and with a single worker Vitest hands that worker every file as one batch in one
       context, where 15 tests failed on state another file left behind. So both projects take WORKERS, never
       fewer than two, and set it per project because Vitest refuses two projects with different counts in one
       group. The cost is that `--maxWorkers` on the command line no longer lowers it. */
    projects: [
      {
        extends: true,
        test: {
          name: 'logic',
          environment: 'node',
          include: ['frontend/**/*.test.ts'],
          maxWorkers: WORKERS,
        },
      },
      {
        extends: true,
        test: {
          name: 'dom',
          environment: 'jsdom',
          include: ['frontend/**/*.test.tsx'],
          pool: 'vmForks',
          maxWorkers: WORKERS,
        },
      },
    ],
    /* `pnpm test:coverage` enforces these locally and the quality gate's frontend coverage job enforces them on
       every PR, where the `coverage-exception` label is the visible bypass, as it is for the Python threshold.
       `include` is every source under `frontend/src`, so a file no test imports counts as uncovered rather than
       absent. It also counts the few test-support modules kept there (the `testing` mounts and the control
       gallery), which can only lower the figures.
       Measured when the gate was added (2026-10-28): 92.8% statements, 86.6% branches, 94.1% functions and
       94.5% lines. */
    coverage: {
      provider: 'v8',
      include: ['frontend/src/**/*.{ts,tsx}'],
      exclude: ['frontend/src/**/*.test.{ts,tsx}', 'frontend/src/**/*.test.helper.{ts,tsx}'],
      reporter: ['text', 'json-summary'],
      reportsDirectory: 'coverage/frontend',
      thresholds: { statements: 80, branches: 80, functions: 80, lines: 80 },
    },
    // A hosted Windows runner took longer than the default five seconds on a generated-board test that
    // takes about one second here; a hang still ends, only later.
    testTimeout: 30_000,
    env: { TZ: 'UTC', LC_ALL: 'en_US.UTF-8', LANG: 'en_US.UTF-8' },
  },
});
