import { expect, it } from 'vitest';
import { linearAsksPlan } from '../../test/plan-fixtures';
import { expirePlanReadings } from './plan';

it('keeps the ask and drops its expired project goal while the milestone is fresh', () => {
  const [project, milestone] = linearAsksPlan.goals;
  const [projectSource, milestoneSource] = linearAsksPlan.sources;
  const plan = {
    ...linearAsksPlan,
    trackerAsksFreshForMs: 30_000,
    trackerRead: {
      ...linearAsksPlan.trackerRead,
      updates: [
        {
          freshForMs: 30_000,
          goals: { remove: [project.id], upsert: [] },
          lanes: { remove: [], upsert: [] },
          sources: [{ ...projectSource, state: 'expired', reason: 'expired' }, milestoneSource],
        },
      ],
    },
  } as const;

  expect(expirePlanReadings(plan, 19_999)).toBe(plan);
  const expired = expirePlanReadings(plan, 20_000);
  expect(expired.goals).toEqual([milestone]);
  expect(expired.trackerAsks).toEqual([
    { ...linearAsksPlan.trackerAsks[0], goals: [milestone.id] },
  ]);
  expect(expired.trackerAsksFreshForMs).toBe(30_000);
  expect(expirePlanReadings(expired, 30_000).trackerAsks).toBeNull();
});
