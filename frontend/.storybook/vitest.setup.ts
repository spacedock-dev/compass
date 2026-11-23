import { afterEach, beforeEach, expect } from 'vitest';
import { commands } from 'vitest/browser';
import budget from '../first-layer-budget.json';
import { auditCalm } from '../stories/calm.audit';
import { firstLayerViolations } from '../test/firstLayer';
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

afterEach(({ task }) => {
  const id = 'storyId' in task.meta ? task.meta.storyId : undefined;
  if (
    typeof id !== 'string' ||
    !(
      id.startsWith('drift-a-level-needs-a-departure--') ||
      id.startsWith('drift-store-refusal--') ||
      id === 'sessions-codex-finished-run--stored-progress-without-a-level' ||
      id ===
        'drift-idle-analysis-and-steer-back--an-out-of-date-check-shows-the-earlier-finding-beside-steering'
    )
  )
    return;
  // These Session stories reach progress states that the recorded boards do not exercise.
  const session = document.querySelector('[data-next-session-detail]');
  expect(session, id).not.toBeNull();
  if (session) expect(firstLayerViolations(session), id).toEqual([]);
});
