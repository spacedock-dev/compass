import { describe, expect, it } from 'vitest';
import { mountPanels } from '../steering/testing';
import { firstShapeDifference, shape } from './dom.test.helper';
import { ProjectConsole } from './Console';
import { genRailCase } from './rail.generate.test.helper';
import { loadLegacyRail } from './legacy.rail.test.helper';
import { restateLiveOpener } from '../../test/recordedCommandOpener';

/* The Console's rail is held to the legacy page by what a reader can read and press. The page's own
   `nextProjectRail` runs over a generated board, after the same two payloads this tab accepted, and so does
   the Console; every project's rail is reduced to the same tree and compared: the delegation figure and its
   window, each waiting session with its controls, each capacity window, and the tripwires panel. A failure
   names the seed, the project and the first path that differs. */
const legacy = loadLegacyRail();
const CASES = 80;
const SEEDS = CASES;

describe('the Console rail agrees with the legacy page', () => {
  it(`over ${String(SEEDS)} generated boards`, async () => {
    const failures: string[] = [];
    const seen = { rails: 0, known: 0, trend: 0, rate: 0, waiting: 0, windows: 0, raise: 0 };
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const generated = genRailCase(seed);
      legacy.reset();
      legacy.setCapability(generated.capability);
      legacy.observe(generated.first);
      legacy.observe(generated.second);
      const projects = legacy.projects(generated.second);
      const page = mountPanels(
        <>
          {projects.map((project) => (
            <section key={project} data-test-project={project}>
              <ProjectConsole project={project} projectKey={project} focus={null} />
            </section>
          ))}
        </>,
        {
          data: generated.first,
          strict: false,
          ...(generated.capability ? { focusCapability: generated.capability } : {}),
        },
      );
      await page.settle();
      await page.poll(generated.second);
      for (const project of projects) {
        const template = document.createElement('template');
        template.innerHTML = legacy.rail(generated.second, project);
        const theirs = template.content.querySelector('aside');
        const mine = [...page.container.querySelectorAll('[data-test-project]')]
          .find((node) => (node as HTMLElement).dataset['testProject'] === project)
          ?.querySelector('aside[data-next-project-rail]');
        if (!theirs || !mine) {
          failures.push(
            `seed ${String(seed)} project ${JSON.stringify(project)}: missing ${theirs ? 'port' : 'legacy'} rail`,
          );
          continue;
        }
        restateLiveOpener(mine);
        const found = firstShapeDifference(shape(theirs), shape(mine));
        if (found)
          failures.push(`seed ${String(seed)} project ${JSON.stringify(project)}: ${found}`);
        seen.rails += 1;
        seen.known += mine.querySelector('[data-next-delegation-percent]') ? 1 : 0;
        seen.trend += mine.querySelector('[data-next-delegation-trend]') ? 1 : 0;
        seen.rate += mine.querySelector('[data-next-delegation-rate]') ? 1 : 0;
        seen.waiting += mine.querySelectorAll('[data-next-wait-session]').length;
        seen.windows += mine.querySelectorAll('[data-next-rail-window]').length;
        seen.raise += mine.querySelectorAll('[data-control="raise"]').length;
      }
      page.unmount();
    }
    expect(failures).toEqual([]);
    // The comparison is not vacuous.
    expect(seen.rails).toBeGreaterThan(50);
    expect(seen.known).toBeGreaterThan(10);
    expect(seen.waiting).toBeGreaterThan(15);
    expect(seen.windows).toBeGreaterThan(10);
    expect(seen.raise).toBeGreaterThan(0);
  }, 240_000);
});
