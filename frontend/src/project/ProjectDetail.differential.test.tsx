import {
  projectWordDeviation,
  projectGlossEnabled,
  projectInstructionHeading,
} from '../../test/projectWordDeviation';
import { describe, expect, it } from 'vitest';
import { disclosureReadings, normalizeDisclosures } from '../../test/disclosures';
import { compatSessKey, exactIdentity } from '../api/identity';
import { arrange, labelsOf } from './arrange.test.helper';
import { genBoard, genContext, parityBoard, scenarios } from './generate.test.helper';
import { sessKey, stableKey } from './group';
import { parseHtml } from './legacy.test.helper';
import { restateLiveOpener } from '../../test/recordedCommandOpener';
import { memoKey } from '../storage';
import { mountProject } from './testing';

/* The project page held to the legacy page by what a reader can read. The legacy `nextProjectView` runs
   unchanged over a generated board and a seeded context read, and this page renders the same board in the
   real shell; both are reduced to the same regions (header, scope, strip, tabs and the current panel) and
   compared region by region. A difference is a bug here unless it is named in DEVIATIONS with its reason.

   Outside the comparison on purpose, because the steering step owns them: the steering bar, the stage
   conditions, and the whole of the Decisions and Console tabs. */

const CASES = 40;
const SEEDS = CASES;

const norm = (node: Element | null): string =>
  node ? (node.textContent ?? '').replace(/\s+/g, ' ').trim() : '';

interface Summary {
  readonly header: string;
  readonly headerAbsent: boolean;
  readonly viewing: string;
  readonly scopeTree: string;
  readonly scopeLinks: readonly (readonly [string | null, string | null, boolean])[];
  readonly switcher: string;
  readonly strip: string;
  readonly stripLinks: readonly (string | null)[];
  readonly stripAttrs: readonly string[];
  readonly tabs: readonly string[];
  readonly panel: string;
  readonly panelLinks: readonly (string | null)[];
  readonly panelKinds: readonly string[];
  readonly disclosures: ReturnType<typeof disclosureReadings>;
}

function summarize(source: Element | DocumentFragment, tab: string): Summary {
  const article = normalizeDisclosures(source);
  const header = article.querySelector('.next-project-detail-header');
  const tree = article.querySelector('nav.next-cockpit-scope-tree');
  const strip = article.querySelector('.next-cockpit-recovery');
  const panel =
    article.querySelector(`[data-next-cockpit-panel="${tab}"]`) ??
    article.querySelector('.next-cockpit-panel');
  return {
    header: norm(header),
    headerAbsent: header?.querySelector('.next-project-value--absent') !== null,
    viewing: norm(article.querySelector('.next-cockpit-viewing-session')),
    scopeTree: norm(tree),
    scopeLinks: [...(tree?.querySelectorAll('a') ?? [])].map(
      (link) =>
        [
          link.getAttribute('href'),
          link.getAttribute('data-scope-kind'),
          link.hasAttribute('aria-current'),
        ] as const,
    ),
    switcher: norm(article.querySelector('.next-cockpit-scope-switcher summary')),
    strip: norm(strip),
    stripLinks: [...(strip?.querySelectorAll('a') ?? [])].map((link) => link.getAttribute('href')),
    stripAttrs: [
      ...(strip?.querySelectorAll(
        '[data-next-cockpit-authority-state],[data-work-item],[data-next-cockpit-task-known]',
      ) ?? []),
    ].map((node) =>
      [
        node.getAttribute('data-next-cockpit-authority-state'),
        node.getAttribute('data-work-item'),
        node.hasAttribute('data-next-cockpit-task-known'),
      ].join('|'),
    ),
    tabs: [...article.querySelectorAll('nav.next-cockpit-tabs [role="tab"]')].map(
      (button) => `${norm(button)}|${String(button.getAttribute('aria-selected'))}`,
    ),
    panel: norm(panel),
    panelLinks: [...(panel?.querySelectorAll('a') ?? [])].map((link) => link.getAttribute('href')),
    panelKinds: [
      ...(panel?.querySelectorAll(
        '[data-next-project-activity],[data-epistemic-kind],[data-scope-kind]',
      ) ?? []),
    ].map(
      (node) =>
        node.getAttribute('data-next-project-activity') ??
        node.getAttribute('data-epistemic-kind') ??
        node.getAttribute('data-scope-kind') ??
        '',
    ),
    disclosures: disclosureReadings(article),
  };
}

/* Named differences, each with its reason. */
const DEVIATIONS: readonly { readonly name: string; readonly reason: string }[] = [];

describe('the project page reads as the legacy page does, over generated boards', () => {
  it(`agrees on ${String(SEEDS)} boards: header, scopes, the recovery strip, the tabs, Now and Course`, async () => {
    const failures: string[] = [];
    let compared = 0;
    const reach: Record<string, number> = {};
    const REACH: readonly (readonly [string, RegExp])[] = [
      ['captain needed', /CAPTAIN NEEDED/],
      ['fo inspecting', /FO INSPECTING/],
      ['continues', /FO CONTINUES|CONTINUES · Continue the current task/],
      ['waiting on you', /WAITING ON YOU/],
      ['child handoff', /Evidence · child handoff/],
      ['assignment from state', /Exact workflow state/],
      ['assignment from direction', /Exact operator direction/],
      ['latest result', /LATEST (?:EXACT|SESSION) RESULT/],
      ['derived course change', /DERIVED COURSE CHANGE/],
      ['exact result', /EXACT RESULT/],
      ['exact decision', /EXACT DECISION/],
      ['other directions', /Other directions/],
      ['going on card', /next ·/],
      ['plan', /PLAN/],
      ['workflow definition', /DECLARED STAGES/],
      ['completed', /COMPLETED TASKS · [1-9]/],
      ['progress', /\d+ of \d+ done/],
      ['stalled', /stalled/],
      ['ended', /HOW THINGS ENDED/],
      ['scope tree', /SCOPE/],
      ['memo field', /OPTIONAL HUMAN NOTE/],
      ['add human context', /Add human context/],
    ];
    const hand = scenarios();
    for (let seed = 1; seed <= SEEDS + hand.length; seed += 1) {
      const scenario = seed > SEEDS ? hand[seed - SEEDS - 1] : undefined;
      const board = scenario ? scenario.board : genBoard(seed);
      const context = scenario ? scenario.context : genContext(seed, board);
      // A project with no label has no route (the router reads `#n=project:` as no project), so it has no page to compare.
      const labels = labelsOf(board).filter(Boolean);
      const label = labels[seed % labels.length];
      if (label === undefined) continue;
      const tab = scenario
        ? scenario.name === 'a long course'
          ? 'course'
          : 'now'
        : seed % 2 === 0
          ? 'course'
          : 'now';
      const variant = seed % 5 === 0 ? 'failed' : seed % 7 === 0 ? 'absent' : 'ready';
      const made = arrange(board, context, label, variant);
      if (!made) continue;
      const rows = made.env.group.sessions;
      const candidate = seed % 3 === 0 && rows.length ? (rows[seed % rows.length] ?? null) : null;
      const focus = candidate && exactIdentity(candidate) ? candidate : null;
      const stable = stableKey(made.env.group);
      // Legacy: the route, the observed workstream buffer, and the focused context read where the tab asks for one.
      const fragment = `#n=project:${encodeURIComponent(label)}${focus ? `:${encodeURIComponent(sessKey(focus))}` : ''}${tab === 'now' ? '' : `:${tab}`}`;
      made.app.setRoute(fragment);
      made.app.observe(board);
      const focusContext = focus ? genContext(seed + 9000, board) : null;
      // The focused read is made by the tabs that need it, so the Now tab has not asked for it yet.
      if (focus && focusContext && tab !== 'now') {
        made.app.setContext(`${stable}\n${sessKey(focus)}`, { data: focusContext, revision: 1 });
      }
      // The legacy lanes read their child-assignment snapshot from a cache keyed by the focused session; this
      // page always reads the project's own, so the legacy cache is given it under that key as well.
      if (focus && made.entry?.data)
        made.app.run('projectContextByLabel[__key] = {state: "ready", data: __data};', {
          key: `${stable}\n${sessKey(focus)}`,
          data: made.entry.data,
        });
      // The reader's own two notes, for some boards: the strip then draws the fields in place of the offer.
      const notes: Record<string, string> = {};
      if (seed % 4 === 0) {
        notes[
          memoKey(
            stable,
            focus
              ? {
                  harness: String(focus['harness'] || ''),
                  sid: String(focus['sid'] || ''),
                  session: String(focus['session'] || ''),
                }
              : null,
            'outcome',
          )
        ] = 'Land the queue';
        notes[
          memoKey(
            stable,
            focus
              ? {
                  harness: String(focus['harness'] || ''),
                  sid: String(focus['sid'] || ''),
                  session: String(focus['session'] || ''),
                }
              : null,
            'focus',
          )
        ] = 'The drain';
        for (const [key, value] of Object.entries(notes))
          made.app.run('nextCockpitMemoDrafts.set(__key, __value);', { key, value });
      }
      const html = made.app.call<string>('nextProjectView', label);
      const legacy = projectWordDeviation(
        summarize(parseHtml(html), tab),
        projectGlossEnabled(board, label),
        [board, context, notes, focusContext],
        projectInstructionHeading(board, label, focus),
      );

      const contexts: Record<string, unknown> = {};
      if (variant === 'ready' && context) contexts[`${stable}\n`] = context;
      if (variant !== 'ready' && variant !== 'absent') {
        /* failed: no answer, so the read is refused */
      }
      if (focus && focusContext && tab !== 'now')
        contexts[`${stable}\n${compatSessKey(focus)}`] = focusContext;
      const page = mountProject({
        hash: fragment,
        data: board,
        contexts,
        strict: false,
        storage: notes,
      });
      // A read nobody has answered yet: the legacy page's entry with no data and no error.
      if (variant === 'absent' || (variant === 'ready' && !context))
        page.state.held.add(`${stable}\n`);
      if (focus && !focusContext) page.state.held.add(`${stable}\n${compatSessKey(focus)}`);
      await page.settle();
      const article = page.container.querySelector('article.next-project-detail');
      if (!article) {
        failures.push(
          `seed ${String(seed)} ${variant}: the page drew no project article for ${JSON.stringify(label)}`,
        );
        page.unmount();
        if (failures.length >= 3) break;
        continue;
      }
      restateLiveOpener(article);
      const mine = summarize(article, tab);
      page.unmount();
      compared += 1;
      for (const [name, pattern] of REACH)
        if (pattern.test(`${legacy.strip} ${legacy.panel} ${legacy.scopeTree}`))
          reach[name] = (reach[name] ?? 0) + 1;
      for (const key of Object.keys(legacy) as (keyof Summary)[]) {
        if (JSON.stringify(legacy[key]) === JSON.stringify(mine[key])) continue;
        if (DEVIATIONS.some((deviation) => deviation.name === `${String(seed)}:${key}`)) continue;
        const left = JSON.stringify(legacy[key]);
        const right = JSON.stringify(mine[key]);
        let at = 0;
        while (left[at] === right[at]) at += 1;
        failures.push(
          `seed ${String(seed)} ${variant} ${tab}${focus ? ' focused' : ''} ${key}: legacy ${JSON.stringify(left.slice(Math.max(0, at - 60), at + 140))} vs ${JSON.stringify(right.slice(Math.max(0, at - 60), at + 140))}`,
        );
      }
      if (failures.length >= 3) break;
    }
    expect(failures).toEqual([]);
    expect(compared).toBeGreaterThan(SEEDS / 2);
    // Agreement means something only where the states were reached. The floor is for the default run.
    if (SEEDS >= 40) for (const [name] of REACH) expect(reach[name] ?? 0, name).toBeGreaterThan(0);
  }, 600_000);
});

describe('the browser proof’s own board reads the same on both pages', () => {
  it('agrees on every project and both tabs, with the context each project has', async () => {
    const { board, contexts } = parityBoard();
    const failures: string[] = [];
    let compared = 0;
    for (const label of labelsOf(board).filter(Boolean)) {
      for (const tab of ['now', 'course'] as const) {
        const stable = String(
          (board['sessions'] as { project?: string; project_key?: string }[]).find(
            (row) => row.project === label,
          )?.project_key || label,
        );
        const context = contexts[stable] ?? null;
        const made = arrange(board, context, label, 'ready');
        if (!made) continue;
        const fragment = `#n=project:${encodeURIComponent(label)}${tab === 'now' ? '' : `:${tab}`}`;
        made.app.setRoute(fragment);
        made.app.observe(board);
        const legacy = projectWordDeviation(
          summarize(parseHtml(made.app.call<string>('nextProjectView', label)), tab),
          projectGlossEnabled(board, label),
          [board, context],
          projectInstructionHeading(board, label),
        );
        const page = mountProject({
          hash: fragment,
          data: board,
          contexts: context ? { [`${stable}\n`]: context } : {},
          strict: false,
        });
        if (!context) page.state.held.add(`${stable}\n`);
        await page.settle();
        const article = page.container.querySelector('article.next-project-detail');
        if (article) restateLiveOpener(article);
        const mine = article ? summarize(article, tab) : null;
        page.unmount();
        compared += 1;
        for (const key of Object.keys(legacy) as (keyof Summary)[])
          if (!mine || JSON.stringify(legacy[key]) !== JSON.stringify(mine[key]))
            failures.push(
              `${label} ${tab} ${key}: ${JSON.stringify(legacy[key])?.slice(0, 160)} vs ${JSON.stringify(mine?.[key])?.slice(0, 160)}`,
            );
      }
    }
    expect(failures).toEqual([]);
    expect(compared).toBeGreaterThanOrEqual(8);
  });
});
