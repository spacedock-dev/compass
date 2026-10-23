import { describe, expect, it } from 'vitest';
import { genPayload } from '../observed/generate.test.helper';
import { restateLiveOpener } from '../../test/recordedCommandOpener';
import { mountShell } from '../shell/testing';
import { genBoard, scenarios } from './generate.test.helper';
import { loadLegacyApp, parseHtml } from './legacy.test.helper';

/* The Projects list held to the legacy list by what a reader can read: each group, each project row in
   order, its text, tone and route, and every member line it names. The legacy `nextProjectsView` runs
   unchanged over a generated board and this list renders the same board in the real shell. The stage
   conditions that open the legacy list belong to the steering step and are drawn by neither side here. */

const CASES = 60;
const SEEDS = CASES;

const norm = (node: Element | null): string =>
  node ? (node.textContent ?? '').replace(/\s+/g, ' ').trim() : '';

interface Summary {
  readonly note: string;
  readonly groups: readonly {
    readonly kind: string;
    readonly header: string;
    readonly empty: string | null;
    readonly rows: readonly {
      readonly project: string;
      readonly route: string | null;
      readonly tone: string;
      readonly history: boolean;
      readonly role: string | null;
      readonly tabindex: string | null;
      readonly text: string;
      readonly members: readonly (readonly [string | null, string | null, string | null, string])[];
      readonly more: string | null;
    }[];
  }[];
}

function summarize(root: ParentNode): Summary {
  return {
    note: norm(root.querySelector('.next-projects-note')),
    groups: [...root.querySelectorAll('[data-next-project-group]')].map((group) => ({
      kind: group.getAttribute('data-next-project-group') ?? '',
      header: norm(group.querySelector(':scope > header')),
      empty: group.querySelector('.next-projects-empty')
        ? norm(group.querySelector('.next-projects-empty'))
        : null,
      rows: [...group.querySelectorAll('article.next-project-row')].map((row) => ({
        project: row.getAttribute('data-next-project') ?? '',
        route: row.getAttribute('data-next-route'),
        tone: [...row.classList].find((name) => name.startsWith('next-project-tone--')) ?? '',
        history: row.getAttribute('data-next-project-history') === 'true',
        role: row.getAttribute('role'),
        tabindex: row.getAttribute('tabindex'),
        text: norm(row),
        members: [...row.querySelectorAll('button.next-project-session')].map(
          (member) =>
            [
              member.getAttribute('data-next-route'),
              member.getAttribute('data-next-harness'),
              member.getAttribute('data-next-session'),
              norm(member),
            ] as const,
        ),
        more: row.querySelector('.next-project-more')
          ? norm(row.querySelector('.next-project-more'))
          : null,
      })),
    })),
  };
}

async function mine(payload: unknown): Promise<Summary> {
  const page = mountShell({ hash: '#n=projects', data: payload, strict: false });
  await page.settle();
  const root = page.container.querySelector('[data-next-view-body="projects"]');
  if (!root) throw new Error('The Projects list did not draw.');
  restateLiveOpener(root);
  const result = summarize(root);
  page.unmount();
  return result;
}

function legacy(payload: unknown): Summary {
  const app = loadLegacyApp();
  app.setData(payload);
  return summarize(parseHtml(app.call<string>('nextProjectsView', {})));
}

describe('the Projects list reads as the legacy list does, over generated boards', () => {
  it(`agrees on ${String(SEEDS)} boards, group by group and row by row`, async () => {
    const failures: string[] = [];
    const hand = scenarios();
    const reach = { active: 0, history: 0, more: 0, shared: 0, risky: 0, ended: 0 };
    for (let seed = 1; seed <= SEEDS + hand.length; seed += 1) {
      const scenario = seed > SEEDS ? hand[seed - SEEDS - 1] : undefined;
      const board = scenario
        ? scenario.board
        : seed % 2
          ? genBoard(seed)
          : genPayload(seed, { wellFormed: true });
      const old = legacy(board);
      const now = await mine(board);
      const text = JSON.stringify(old);
      reach.active += (text.match(/"kind":"active"/g) ?? []).length;
      reach.history += (text.match(/"history":true/g) ?? []).length;
      reach.more += (text.match(/other sessions?"/g) ?? []).length;
      reach.shared += (text.match(/share this display label/g) ?? []).length;
      reach.ended += (text.match(/ended/g) ?? []).length;
      if (JSON.stringify(old) !== JSON.stringify(now)) {
        const left = JSON.stringify(old);
        const right = JSON.stringify(now);
        let at = 0;
        while (left[at] === right[at]) at += 1;
        failures.push(
          `seed ${String(seed)}: differs near ${JSON.stringify(left.slice(Math.max(0, at - 90), at + 160))} vs ${JSON.stringify(right.slice(Math.max(0, at - 90), at + 160))}`,
        );
      }
      if (failures.length >= 3) break;
    }
    expect(failures).toEqual([]);
    for (const [name, count] of Object.entries(reach))
      if (name !== 'risky') expect(count, name).toBeGreaterThan(2);
  }, 300_000);
});
