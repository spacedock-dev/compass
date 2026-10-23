import { describe, expect, it } from 'vitest';
import { instructionSourceDeviation } from '../../test/projectWordDeviation';
import { nextNumber } from '../api/bootstrap';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import { restateLiveOpenerValue } from '../../test/recordedCommandOpener';
import { completedTasks, progressValue, projectMembers, projectProgress } from './activity';
import { genBoard, genContext } from './generate.test.helper';
import { entityState, planEmptyText, projectPlans, unhealthyCount } from './plans';
import { arrange, labelsOf } from './arrange.test.helper';

/* The pure halves of the project views (plans, members, progress, completed work), held to the legacy
   functions over the same boards and contexts the recovery test uses. The functions that return markup
   are compared where they are drawn, in the view differential. */

const CASES = 40;
const SEEDS = CASES;

describe('the project model reads as the legacy model does', () => {
  it(`agrees on ${String(SEEDS)} generated boards: plans, entity health, members, progress, completed work`, () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const board = genBoard(seed);
      const context = genContext(seed, board);
      for (const label of labelsOf(board)) {
        const made = arrange(board, context, label, seed % 4 === 0 ? 'absent' : 'ready');
        if (!made) continue;
        const { app, legacyGroup, env, entry } = made;
        const at = `seed ${String(seed)} ${JSON.stringify(label)}`;
        const check = (name: string, left: unknown, right: unknown) => {
          const found = firstDifference(canonical(left), canonical(right));
          if (found) failures.push(`${at} ${name}: ${found}`);
        };
        try {
          const rows = env.group.sessions;
          const plans = projectPlans(rows);
          const legacyPlans = app.run<{ entities: unknown[] }[]>(
            'nextProjectPlans(__group.sessions)',
            {
              group: legacyGroup,
            },
          );
          check('plans', legacyPlans, plans);
          const generated = nextNumber(board['generated']);
          check(
            'entity states',
            legacyPlans.flatMap((plan) =>
              plan.entities.map((entity) =>
                app.run('nextProjectEntityState(__entity)', { entity }),
              ),
            ),
            plans.flatMap((plan) => plan.entities.map((entity) => entityState(entity, generated))),
          );
          check(
            'unhealthy',
            app.run('nextProjectUnhealthyCount(__plans)', { plans: legacyPlans }),
            unhealthyCount(plans, generated),
          );
          check(
            'empty text',
            app.run('nextProjectEmptyState({group: __group}, __observation)', {
              group: legacyGroup,
              observation: entry?.data ?? null,
            }),
            planEmptyText(rows, entry?.data ?? null),
          );
          const observed = env.group.observed;
          const legacyObserved = app.run<{ sessions: unknown[]; risky: unknown[] }>(
            'nextCurrentObserved().projects.find(project => project.key === __label)',
            { label },
          );
          check(
            'members',
            instructionSourceDeviation(
              app.run('nextProjectMembers(__project.sessions, __project.risky || [])', {
                project: legacyObserved,
              }),
            ),
            restateLiveOpenerValue(projectMembers(observed.sessions, observed.risky)),
          );
          check(
            'completed',
            app.run('nextProjectCompletedTasks(__project.sessions)', { project: legacyObserved }),
            completedTasks(observed.sessions),
          );
          check(
            'completed gate',
            app.run('nextProjectCompletedTasks(__group.sessions)', { group: legacyGroup }),
            completedTasks(rows),
          );
          // The legacy bar is markup; its two numbers and its sentence are what is compared.
          const html = app.run<string>('nextProjectProgress(__group.sessions)', {
            group: legacyGroup,
          });
          const progress = projectProgress(rows);
          const parsed = /value="([^"]*)" max="([^"]*)" aria-label="([^"]*)"/.exec(html);
          check(
            'progress',
            parsed ? { value: parsed[1], max: parsed[2], label: parsed[3] } : null,
            progress
              ? {
                  value: String(progressValue(progress)),
                  max: String(progress.total),
                  label: `${String(progress.done)} of ${String(progress.total)} tasks done`,
                }
              : null,
          );
        } catch (error) {
          failures.push(`${at}: threw ${String((error as Error).stack ?? error).slice(0, 400)}`);
        }
        if (failures.length >= 3) break;
      }
      if (failures.length >= 3) break;
    }
    expect(failures).toEqual([]);
  }, 300_000);

  it('reaches plans, unhealthy entities, hidden members and progress, so agreement means something', () => {
    const seen = {
      plans: 0,
      entities: 0,
      blocked: 0,
      stalled: 0,
      hidden: 0,
      progress: 0,
      completed: 0,
      empty: 0,
    };
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const board = genBoard(seed);
      for (const label of labelsOf(board)) {
        const made = arrange(board, genContext(seed, board), label, 'ready');
        if (!made) continue;
        const { env } = made;
        const generated = nextNumber(board['generated']);
        const plans = projectPlans(env.group.sessions);
        seen.plans += plans.length;
        if (plans.length === 0) seen.empty += 1;
        for (const plan of plans)
          for (const entity of plan.entities) {
            seen.entities += 1;
            const state = entityState(entity, generated);
            if (state.label === 'blocked on you') seen.blocked += 1;
            if (state.label.startsWith('stalled')) seen.stalled += 1;
          }
        if (projectMembers(env.group.observed.sessions, env.group.observed.risky).hidden > 0)
          seen.hidden += 1;
        if (projectProgress(env.group.sessions)) seen.progress += 1;
        if (completedTasks(env.group.observed.sessions).length) seen.completed += 1;
      }
    }
    for (const [name, count] of Object.entries(seen)) expect(count, name).toBeGreaterThan(0);
  });
});
