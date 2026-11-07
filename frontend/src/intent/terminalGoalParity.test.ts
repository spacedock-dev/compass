import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it, vi } from 'vitest';
import * as observed from '../observed';
import type { Row } from '../observed';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { annotationLines, annotationOf } from './annotation';
import { goalBaseline, goalSourceLine } from './derive';
import { createHeld } from './held';

// Inputs were recorded from the real loopback server over captured transcript shapes.
// Expected text comes from the page with no browser edits held. Clock formatting is injected
// in both languages so a contributor's timezone cannot change these answers.
const path = resolve('frontend/test/fixtures/terminal-goal.json');
it('a person reads the fresh Intent goal, source and outcomes in the terminal', () => {
  const clock = vi.spyOn(observed, 'clock').mockReturnValue('03:04');
  try {
    const cases = JSON.parse(readFileSync(path, 'utf8')) as {
      name: string;
      payload: Row;
      expected?: unknown;
    }[];
    for (const item of cases) {
      const session = item.payload['session'] as Row;
      const annotation = annotationOf(session);
      const held = createHeld({ clock: createFakeClock(), announcer: createAnnouncer() });
      const input = { held, payload: item.payload, session, annotation, contexts: new Map() };
      const actual = {
        goal: goalBaseline(input),
        source: goalSourceLine(input),
        outcomes: annotationLines(annotation).map((line) => line.text),
      };
      if (item.name === 'harness-goal-draft' || item.name === 'adopted-harness-goal') {
        const harnessGoal = session['session_goal'] as Row;
        expect(harnessGoal, item.name).toBeTruthy();
        expect(actual.goal, item.name).toBe(harnessGoal['text']);
        expect(actual.goal, item.name).not.toBe(session['first_prompt']);
        expect(actual.source, item.name).toBe(
          item.name === 'harness-goal-draft'
            ? 'From your /goal at 03:04 · not saved'
            : 'From your /goal at 03:04 · saved',
        );
      }
      if (process.env['COMPASS_WRITE_GOAL_PARITY'] === '1') item.expected = actual;
      expect(actual, item.name).toEqual(item.expected);
    }
    if (process.env['COMPASS_WRITE_GOAL_PARITY'] === '1') {
      writeFileSync(path, `${JSON.stringify(cases, null, 2)}\n`);
    }
  } finally {
    clock.mockRestore();
  }
});
