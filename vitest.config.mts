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

       The jsdom project runs in VM contexts inside long-lived workers. Each file still gets its own jsdom window
       and module graph, but jsdom and the source files are loaded once per worker rather than once per file:
       the whole suite went from 101 to 63 seconds on two workers (measured 2026-10-28). The logic project stays
       on plain forks, because a VM context gives it a second realm: `toBeInstanceOf(Array)` failed on an array
       built in the test, and Vite's native bundler refused plugin objects made inside the context. */
    projects: [
      {
        extends: true,
        test: { name: 'logic', environment: 'node', include: ['frontend/**/*.test.ts'] },
      },
      {
        extends: true,
        test: {
          name: 'dom',
          environment: 'jsdom',
          include: ['frontend/**/*.test.tsx'],
          pool: 'vmForks',
        },
      },
    ],
    coverage: {
      exclude: ['frontend/stories/**', 'frontend/.storybook/**', 'frontend/storybook/**'],
    },
    // A hosted Windows runner took longer than the default five seconds on a generated-board test that
    // takes about one second here; a hang still ends, only later.
    testTimeout: 30_000,
    env: { TZ: 'UTC', LC_ALL: 'en_US.UTF-8', LANG: 'en_US.UTF-8' },
  },
});
