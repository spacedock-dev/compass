import { afterEach, expect } from 'vitest';

/* Testing Library and its matchers are loaded only where there is a DOM to test. The logic project runs under
   Node, and importing them into each of its files cost more setup time than those files spend testing. */
if (typeof document !== 'undefined') {
  /* Each file must start in a fresh global. The jsdom project's VM pool gives it one per file only with two or
     more workers, and `--no-file-parallelism` forces one whatever the config says; the files then share a
     context, and 15 tests failed on state another file left behind. Say so instead. */
  const context = globalThis as { compassTestContext?: string };
  if (context.compassTestContext)
    throw new Error(
      'A second test file ran in the global of an earlier one. The jsdom tests need a context per file: run ' +
        'them with at least two workers, and without --no-file-parallelism.',
    );
  context.compassTestContext = 'claimed';
  const [{ cleanup }, { toBeInTheDocument, toBeVisible }] = await Promise.all([
    import('@testing-library/react'),
    import('@testing-library/jest-dom/matchers'),
  ]);
  expect.extend({ toBeInTheDocument, toBeVisible });
  afterEach(cleanup);
}

/* jsdom has no scrollIntoView. Disclosure calls it two animation frames after a trigger press, so a test that opens
   one without stubbing it threw an uncaught error whenever those frames landed after the test, and failed CI on
   timing alone (SessionsView.test.tsx, 2026-10-22). Tests that assert on scrolling still install their own spy, and
   files that run without a DOM have no Element to patch. */
if (typeof Element !== 'undefined' && typeof Element.prototype.scrollIntoView !== 'function')
  Element.prototype.scrollIntoView = () => undefined;
