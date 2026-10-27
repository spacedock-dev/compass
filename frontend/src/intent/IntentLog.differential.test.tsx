import { describe, expect, it } from 'vitest';
import { genLogCase, type LogCase } from './generate.test.helper';
import { loadLegacyIntent } from './legacy.test.helper';
import { json, mountIntent } from './testing';
import { maskRevisionWords } from '../../test/revisionWordDeviation';

/* The Intent log, held to the legacy page by what a reader can read. The legacy `nextIntentView` runs
   unchanged over a generated board and a generated set of retained rows; this view renders the same two
   in the real shell; both are reduced to the same shape (the notes in order, each group, each row's
   cells, its link and its words) and compared. A difference is a bug here unless DEVIATIONS names it. */

const legacy = loadLegacyIntent();

interface RowShape {
  readonly cells: readonly (readonly [string, string])[];
  readonly href: string | null;
  readonly linkText: string | null;
}

interface LogShape {
  readonly head: string;
  readonly blocks: readonly (
    | { readonly kind: 'note'; readonly text: string }
    | { readonly kind: 'group'; readonly title: string }
    | ({ readonly kind: 'row' } & RowShape)
  )[];
}

const norm = (node: Element | null): string =>
  node ? (node.textContent ?? '').replace(/\s+/g, ' ').trim() : '';

function shape(root: Element): LogShape {
  const blocks: LogShape['blocks'][number][] = [];
  for (const child of [...root.children]) {
    if (child.tagName === 'H1') continue;
    if (child.tagName === 'H2') blocks.push({ kind: 'group', title: norm(child) });
    else if (child.classList.contains('next-intent-row')) {
      const link = child.querySelector('a');
      blocks.push({
        kind: 'row',
        cells: [...child.children].map(
          (cell) => [cell.className, norm(cell)] as readonly [string, string],
        ),
        href: link?.getAttribute('href') ?? null,
        linkText: link ? norm(link) : null,
      });
    } else blocks.push({ kind: 'note', text: norm(child) });
  }
  return { head: norm(root.querySelector('h1')), blocks };
}

function legacyShape(input: LogCase): LogShape {
  legacy.setData(input.payload);
  legacy.run(
    'nextIntentRows = __rows; nextIntentState = __state; nextRoute = {view: "intent", project: "", session: ""};',
    { rows: input.state === 'read' ? input.rows : null, state: input.state },
  );
  const template = document.createElement('template');
  template.innerHTML = legacy.call<string>('nextIntentView');
  const root = template.content.firstElementChild;
  if (!root) throw new Error('The legacy view drew nothing.');
  return shape(root);
}

async function reactShape(input: LogCase): Promise<LogShape> {
  const page = mountIntent({
    hash: '#n=intent',
    data: input.payload,
    strict: false,
    routes: {
      '/api/annotations': () =>
        input.state === 'error'
          ? json({}, 500)
          : input.state === 'loading'
            ? 'hold'
            : input.state === 'unread'
              ? 'hold'
              : json({ annotations: input.rows, intent_revision: 'r1' }),
    },
  });
  await page.settle();
  await page.settle();
  const root = page.container.querySelector('[data-next-view-body="intent"]');
  if (!root) throw new Error('The Intent log did not draw.');
  const result = shape(root);
  page.unmount();
  return result;
}

const REACHED = {
  rows: 0,
  departed: 0,
  discarded: 0,
  error: 0,
  unread: 0,
  retained: 0,
  empty: 0,
  off: 0,
};

const DEVIATIONS: readonly { readonly seed: number; readonly reason: string }[] = [];

describe('the Intent log reads as the legacy log does, over generated boards', () => {
  const CASES = 80;
  const SEEDS = CASES;
  it(`agrees on ${String(SEEDS)} seeds, note by note and row by row`, async () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const input = genLogCase(seed);
      // The legacy page shows "unread" and "loading" the same way (it has no rows), so one request that
      // never answers stands for both here.
      const old = legacyShape(input);
      const mine = await reactShape(input);
      for (const block of old.blocks) {
        if (block.kind === 'row') {
          REACHED.rows += 1;
          if (block.cells.some(([, text]) => text.startsWith('Your words'))) REACHED.discarded += 1;
          if (block.cells.some(([, text]) => text.startsWith('Typed goal'))) REACHED.retained += 1;
        } else if (block.kind === 'group' && block.title.startsWith('Retained'))
          REACHED.departed += 1;
        else if (block.kind === 'note') {
          if (block.text.startsWith('The annotation store could not')) REACHED.error += 1;
          if (block.text === 'Reading the annotation store.') REACHED.unread += 1;
          if (block.text.startsWith('No goal or expected')) REACHED.empty += 1;
          if (block.text.startsWith('Annotations are off')) REACHED.off += 1;
        }
      }
      if (
        maskRevisionWords(JSON.stringify(old)) !== maskRevisionWords(JSON.stringify(mine)) &&
        !DEVIATIONS.some((d) => d.seed === seed)
      ) {
        const left = JSON.stringify(old);
        const right = JSON.stringify(mine);
        let at = 0;
        while (left[at] === right[at]) at += 1;
        failures.push(
          `seed ${String(seed)} (${input.state}): near ${JSON.stringify(left.slice(Math.max(0, at - 80), at + 140))} vs ${JSON.stringify(right.slice(Math.max(0, at - 80), at + 140))}`,
        );
      }
      if (failures.length >= 3) break;
    }
    expect(failures).toEqual([]);
    // Agreement over a corpus that never reached a state proves nothing about it.
    for (const [name, count] of Object.entries(REACHED)) expect(count, name).toBeGreaterThan(0);
  }, 180_000);
});
