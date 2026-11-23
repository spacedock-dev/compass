import { afterEach, beforeEach, expect } from 'vitest';
import { commands } from 'vitest/browser';
import budget from '../first-layer-budget.json';
import { auditCalm } from '../stories/calm.audit';
import { boardCopyViolations } from '../test/firstLayer';
import {
  auditContrast,
  formatFailures,
  settled,
  unexpectedlyUnmeasured,
} from '../stories/a11y.audit';

declare module 'vitest/browser' {
  interface BrowserCommands {
    storyForcedColors(forcedColors: 'active' | 'none' | null): Promise<void>;
    storyGuard(): Promise<string>;
    storyResult(): Promise<string[]>;
    storyScreenshot(selector: string): Promise<string>;
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
  expect(
    unexpectedlyUnmeasured(report),
    'Text the audit cannot measure (add it to UNMEASURED_ALLOWED with the reason, or fix it)',
  ).toEqual([]);
});

afterEach(async ({ task }) => {
  const id = 'storyId' in task.meta ? task.meta.storyId : undefined;
  expect(id, 'Storybook must identify the story for the first-layer audit').toEqual(
    expect.any(String),
  );
  if (typeof id !== 'string' || budget.stories.some((legacy) => legacy === id)) return;
  await settled();
  const failures = auditCalm(document.body);
  expect(failures, `${id}\n${failures.join('\n')}`).toEqual([]);
});

afterEach(async () => {
  await settled();
  const surfaces = document.querySelectorAll(
    '[data-next-view-body="sessions"], [data-next-session-detail], [data-next-view-body="help"], [data-next-view-body="projects"], [data-next-view-body="project"], [data-sample-invite]',
  );
  for (const surface of surfaces) expect(boardCopyViolations(surface)).toEqual([]);
});
