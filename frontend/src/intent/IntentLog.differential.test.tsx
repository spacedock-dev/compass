import { fireEvent, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { genLogCase, type LogCase } from './generate.test.helper';
import { loadLegacyIntent } from './legacy.test.helper';
import { json, mountIntent } from './testing';

/* The 2026-11-23 redesign changes the row layout and storage wording. Compare goal text,
   exact session links, group membership and load states against the recorded page. */
const legacy = loadLegacyIntent();

interface RowShape {
  readonly href: string | null;
  readonly title: string;
  readonly goal: string;
  readonly discarded: boolean;
}

const norm = (node: Element | null): string =>
  (node?.textContent ?? '').replace(/\s+/g, ' ').trim();

const NOTICES = [
  [/^(?:Annotations are off|Saving goals is off)/, 'off'],
  [/^(?:The annotation store could not|Compass could not read your saved goals)/, 'error'],
  [/^(?:Reading the annotation store|Loading saved goals)/, 'loading'],
] as const;

function shape(root: Element, recorded: boolean) {
  const rows = [...root.querySelectorAll('.next-intent-row')].map((row): RowShape => {
    const link = row.querySelector('a');
    const cells = [...row.querySelectorAll('.next-intent-words')].map(norm);
    const published = cells.find((line) => /^(?:Typed goal|Goal from .*?):/.test(line));
    const saved = published?.replace(/^.*?:\s*/, '') ?? '';
    const validSaved = saved !== 'No goal typed for this session.' ? saved : '';
    const cached =
      cells
        .find((line) => line.startsWith('Cached deterministic goal: '))
        ?.slice('Cached deterministic goal: '.length) ?? '';
    const validCached = cached !== 'No cached deterministic goal available.' ? cached : '';
    const workflow = cells.find(
      (line) =>
        /^Workflow .*?:/.test(line) &&
        !line.endsWith('No workflow goal published.') &&
        !line.endsWith('Spacedock is off for this run.'),
    );
    const discarded = recorded
      ? cells.some((line) => line.startsWith('Your words:'))
      : norm(row.querySelector('[data-next-goal-history-source]')).startsWith(
          'You discarded this goal',
        );
    return {
      href: link?.getAttribute('href') ?? null,
      title: norm(link),
      goal: discarded
        ? ''
        : recorded
          ? validSaved || validCached || (workflow?.replace(/^.*?:\s*/, '') ?? '')
          : norm(row.querySelector('[data-next-goal-history-words]')),
      discarded,
    };
  });
  const words = [...root.children].map(norm);
  return {
    title: norm(root.querySelector('h1')).replace(/^Intent log$/, 'Goal history'),
    groups: [...root.querySelectorAll('h2')].map((h) =>
      norm(h)
        .replace(/^On the board$/, 'On the board now')
        .replace(/^Retained after leaving the board$/, 'Older sessions'),
    ),
    notice: NOTICES.find(([pattern]) => words.some((word) => pattern.test(word)))?.[1] ?? '',
    rows,
  };
}
type LogShape = ReturnType<typeof shape>;

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
  return shape(root, true);
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
  for (const button of within(root as HTMLElement).queryAllByRole('button', {
    name: /^Show \d+ more$/,
  }))
    fireEvent.click(button);
  const result = shape(root, false);
  page.unmount();
  return result;
}

describe('Goal history preserves recorded goal words and session identity', () => {
  it('agrees across 80 seeded boards after masking the redesigned wording', async () => {
    const reached = new Set<string>();
    const failures: string[] = [];
    for (let seed = 1; seed <= 80; seed += 1) {
      const input = genLogCase(seed);
      const old = legacyShape(input);
      const mine = await reactShape(input);
      reached.add(old.notice);
      if (old.rows.some((row) => row.discarded)) reached.add('discarded');
      if (old.rows.some((row) => row.goal)) reached.add('goal');
      if (old.groups.includes('Older sessions')) reached.add('older');
      if (JSON.stringify(old) !== JSON.stringify(mine))
        failures.push(`Seed ${seed}: ${JSON.stringify({ old, mine })}`);
    }
    expect(failures.slice(0, 5)).toEqual([]);
    expect([...reached]).toEqual(
      expect.arrayContaining(['off', 'error', 'loading', 'discarded', 'goal', 'older']),
    );
  }, 180_000);
});
