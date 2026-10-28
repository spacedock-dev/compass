import { afterEach, expect } from 'vitest';

/* Testing Library and its matchers are loaded only where there is a DOM to test. The logic project runs under
   Node, and importing them into each of its files cost more setup time than those files spend testing. */
if (typeof document !== 'undefined') {
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
