import { afterEach, beforeEach, expect } from 'vitest';
import { commands } from 'vitest/browser';
import { auditContrast, formatFailures, settled } from '../stories/a11y.audit';

declare module 'vitest/browser' {
  interface BrowserCommands {
    storyGuard(): Promise<string>;
    storyResult(): Promise<string[]>;
  }
}
beforeEach(async () => {
  const css = await commands.storyGuard();
  if (!document.getElementById('story-fonts')) {
    const style = document.createElement('style');
    style.id = 'story-fonts';
    style.textContent = css;
    document.head.append(style);
  }
});
afterEach(async () => {
  expect(
    await commands.storyResult(),
    'Every story renders offline without console or page errors',
  ).toEqual([]);
});

/* Every story is held to the contrast floor in the state it ends in: 4.5:1 for text, 3:1 for large text and
   glyphs. The measurement and what it leaves out are in `stories/a11y.audit.ts`. */
afterEach(async () => {
  await settled();
  const report = auditContrast(document.body);
  expect(report.failures, formatFailures(report)).toEqual([]);
});
