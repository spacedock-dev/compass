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
        // The waiting rail clamps a question to three lines, where the retired page drew it whole: see
        // docs/design-frontend-migration.md#held-to-recorded-answers (2026-11-12 and 2026-11-23).
        for (const question of mine.querySelectorAll('.next-rail-question')) {
          question.classList.remove('line-clamp-3');
          question.removeAttribute('data-authored');
        }
        for (const title of mine.querySelectorAll('.next-rail-wait-heading a > span'))
          title.replaceWith(...title.childNodes);
        for (const [panel, label] of [
          ['delegation', 'Time agents worked on their own'],
          ['waiting', 'Waiting on you'],
          ['capacity', 'Your AI allowance'],
          ['tripwires', 'Tripwires'],
        ] as const) {
          const heading = theirs.querySelector(`[data-next-rail-panel="${panel}"] header h2`);
          if (heading) heading.textContent = label;
        }
        const allowance = theirs.querySelector('[data-next-rail-panel="capacity"]');
        const caption = allowance?.querySelector('header .next-rail-meta');
        if (caption) caption.textContent = 'Each plan window resets on its own schedule';
        for (const reason of allowance?.querySelectorAll(':scope > .next-rail-reason') ?? []) {
          if (reason.textContent === 'No quota windows published.')
            reason.textContent = 'No plan usage has been reported yet.';
          else if (reason.textContent === 'No vendor window has been read for this harness.')
            reason.remove();
        }
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
