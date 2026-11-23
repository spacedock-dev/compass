import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import declared from '../../test/fixtures/declared-sessions.json';
import { projectRequestBoard, projectStatusBoard } from '../../test/project_boards';
import { mountProject } from './testing';

/* Keyboard focus on the Projects list is kept by the member button's own node surviving a refresh (see the
   Keyboard focus row of docs/design-reader-state.md), so a member line's key must not move when another
   session joins above it. */

const session = (sid: string, state: string, last: number) => ({
  harness: 'codex',
  sid,
  project: 'alpha/app',
  title: `Session ${sid}`,
  state,
  active: state === 'working',
  last_activity: last,
});

const member = (sid: string): HTMLElement => {
  const found = document.querySelector<HTMLElement>(
    `button.next-project-session[data-next-session="${sid}"]`,
  );
  if (!found) throw new Error(`No member line for ${sid}.`);
  return found;
};

it('counts idle sessions as quiet only when their rows show Quiet', async () => {
  const page = mountProject({ hash: '#n=projects', data: projectStatusBoard });
  await page.settle();
  expect(member('stopped').querySelector('[aria-label="Quiet"]')).not.toBeNull();
  expect(member('scan').querySelector('[aria-label="Quiet"]')).toBeNull();
  expect(member('scan').textContent).toContain(
    'Read by scanning: no turn end can be observed here',
  );
  expect(page.container.querySelector('.next-project-summary')?.textContent).toBe(
    '3 sessions · 1 working · 1 quiet · 1 in no counted state',
  );
});

it.each([
  {
    name: 'a parent waiting on its child',
    data: declared.payload,
    project: 'demo',
    sid: 'parent',
    state: null,
    counts: '3 sessions · 1 working · 2 in no counted state',
  },
  {
    name: 'an exact request after a turn stop',
    data: projectRequestBoard,
    project: 'rollup',
    sid: 'stopped',
    state: 'Waiting on you',
    counts: '2 sessions · 1 working · 1 waiting on you',
  },
])('counts $name once from the state shown on both project views', async (scenario) => {
  const page = mountProject({ hash: '#n=projects', data: scenario.data });
  await page.settle();
  const checkState = (row: HTMLElement) => {
    const icon = within(row).queryByRole('img');
    expect(icon?.getAttribute('aria-label') ?? null).toBe(scenario.state);
    if (scenario.state === null)
      expect(row.textContent).toContain('Waiting on child "Check build"');
  };
  checkState(member(scenario.sid));
  expect
    .soft(page.container.querySelector('.next-project-summary')?.textContent)
    .toBe(scenario.counts);

  fireEvent.click(screen.getByText(scenario.project, { selector: 'strong' }));
  await page.settle();
  const detailRow = page.container.querySelector<HTMLElement>(
    `[data-next-going-on="${scenario.sid}"]`,
  );
  if (!detailRow) throw new Error(`Missing activity row for ${scenario.sid}`);
  checkState(detailRow);
  expect(page.container.querySelector('.next-project-detail-count')?.textContent).toBe(
    scenario.counts,
  );
});

describe('the Projects list keeps a member line through a refresh', () => {
  it('keeps keyboard focus on a member when a session joins above it', async () => {
    const page = mountProject({
      hash: '#n=projects',
      data: {
        generated: 1000,
        sessions: [session('s1', 'working', 990), session('s2', 'idle', 980)],
      },
    });
    await page.settle();
    const focused = member('s2');
    focused.focus();
    await page.poll({
      generated: 1010,
      sessions: [
        session('s1', 'working', 990),
        session('s2', 'idle', 980),
        session('s3', 'needs_input', 1005),
      ],
    });
    const lines = [...document.querySelectorAll('button.next-project-session')].map((line) =>
      line.getAttribute('data-next-session'),
    );
    expect(lines).toEqual(['s3', 's1', 's2']);
    expect(member('s2')).toBe(focused);
    expect(document.activeElement).toBe(focused);
  });

  it('draws both lines of a harness and sid the board published twice', async () => {
    const page = mountProject({
      hash: '#n=projects',
      data: {
        generated: 1000,
        sessions: [session('s1', 'working', 990), session('s1', 'working', 980)],
      },
    });
    await page.settle();
    expect(document.querySelectorAll('button.next-project-session')).toHaveLength(2);
  });
});
