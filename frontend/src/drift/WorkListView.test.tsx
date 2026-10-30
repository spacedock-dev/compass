import type { ProjectContext } from '../api/types';
import { act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { check, fact, jumpTo, mountDrift, press } from './testing';

/* The session's activity list reads newest first. The numbers are the oldest-first ones every "#<n>" and
   every citation names, so the column reads from the highest down to #1 and a reader opens on what just
   happened. Entries are numbered in time order whatever kind they are, so a check sits between the prompts
   either side of it rather than after all of them. */
const FACTS = [
  fact('p1', 900, { summary: 'First direction' }),
  check('c1', 910, 'passed'),
  fact('p2', 920, { summary: 'Second direction' }),
  fact('p3', 996, { summary: 'Newest direction' }),
];
const session = { annotation_goal_saved_at: 500, annotation_at: 500 };

describe('the session activity list', () => {
  it('reads newest first, each row keeping the number its time earned', async () => {
    const page = mountDrift({ facts: FACTS, session });
    await page.settle();
    await page.settle();
    const rows = [...document.querySelectorAll<HTMLElement>('[data-next-entry-id]')];
    expect(rows.map((row) => row.dataset['nextEntryId'])).toEqual(['p3', 'p2', 'c1', 'p1']);
    expect(rows.map((row) => row.dataset['nextEntry'])).toEqual(['4', '3', '2', '1']);
  });

  it('draws "Add to my intent" at rest, with nothing hiding it until the pointer arrives', async () => {
    const page = mountDrift({ facts: FACTS, session });
    await page.settle();
    await page.settle();
    const adds = [
      ...document.querySelectorAll<HTMLElement>('[data-next-cockpit-action="direction-add"]'),
    ];
    expect(adds.length).toBeGreaterThan(0);
    for (const add of adds) {
      expect(add.className).not.toMatch(/opacity-0|hover:opacity|group-hover/);
      expect(add.hidden).toBe(false);
    }
  });

  it('sees short check marks with full accessible words, and time in the head beside Last turn', async () => {
    const page = mountDrift({
      facts: [
        fact('p1', 900),
        check('c1', 910, '', {
          result_source: '',
          before_last_change: true,
          earlier_failed: true,
        }),
      ],
      session: { ...session, annotation_window_start: 500 },
    });
    await page.settle();
    await page.settle();
    const row = document.querySelector('[data-next-entry-id="c1"]') as HTMLElement;
    const head = row.querySelector('.next-cockpit-work-head') as HTMLElement;
    expect(head.textContent).toContain('No result');
    expect(head.querySelector('[aria-label="Ran, result not recorded"]')).not.toBeNull();
    expect(head.querySelector('[aria-label="Before the last change"]')).not.toBeNull();
    expect(head.querySelector('[aria-label="An earlier run failed"]')).not.toBeNull();
    expect(head.querySelector('[aria-label="from the last turn"]')?.textContent).toBe('Last turn');
    expect(head.querySelector('.next-cockpit-work-at')?.textContent).toBe('1m ago');
    expect(row.querySelector('.next-cockpit-work-body > .next-cockpit-work-at')).toBeNull();
    expect(row.getAttribute('data-next-entry-words')).toBe(
      'Agent · check · ran, result not recorded · an earlier run failed · before the last change',
    );
    for (const mark of head.querySelectorAll<HTMLElement>('[data-activity-mark]')) {
      expect(mark.tagName).toBe('SPAN');
      expect(mark.tabIndex).toBe(-1);
      expect(mark.className).not.toMatch(/hidden|opacity-0|hover:opacity|group-hover/);
      expect(mark.querySelector('svg')?.dataset['icon']).toBe(mark.dataset['activityMark']);
    }
    const unknown = head.querySelector('[data-icon="unrecorded"]') as SVGElement;
    expect(unknown.querySelector('path')?.getAttribute('d')).toBe(
      'M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Z',
    );
    expect(unknown.innerHTML).not.toContain('polyline');
    expect(head.querySelector('[data-activity-head-right]')?.className).toContain('ml-auto');
    expect(row.querySelector('.next-cockpit-work-summary')?.textContent).toBe('pytest');
    await press(
      [...document.querySelectorAll('button')].find((button) =>
        button.textContent?.includes('About this record'),
      ) ?? null,
    );
    const legend = document.querySelector('[data-activity-legend]');
    expect(legend?.textContent).toContain('Failed checks are always listed and never folded.');
    expect(legend?.querySelectorAll('li')).toHaveLength(7);
  });

  it('reads Agent said once and keeps an unpublished time in the head', async () => {
    const page = mountDrift({
      facts: [fact('a1', 910, { type: 'agent_message', by: 'agent', summary: 'Done' })],
      session,
    });
    await page.settle();
    await page.settle();
    const head = document.querySelector('[data-next-entry-id="a1"] .next-cockpit-work-head');
    expect(head?.querySelector('.next-cockpit-work-actor')?.textContent).toBe('Agent');
    expect(head?.querySelector('.next-cockpit-work-type')?.textContent).toBe('said');
    expect(head?.textContent).not.toContain('AgentAgent');
  });

  it('keeps a fold open across a board refresh, remount and a new check at the newest end', async () => {
    const facts = [1, 2, 3].map((n) => check(`c${String(n)}`, 900 + n, '', { result_source: '' }));
    const page = mountDrift({ facts, session });
    await page.settle();
    await page.settle();
    const trigger = () => document.querySelector<HTMLButtonElement>('[data-check-run] button');
    expect(trigger()?.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelectorAll('[data-next-entry-id]')).toHaveLength(3);
    await press(trigger());
    expect(trigger()?.getAttribute('aria-expanded')).toBe('true');
    const original = page.state.data;
    await page.poll(original);
    expect(trigger()?.getAttribute('aria-expanded')).toBe('true');
    facts.push(check('c4', 904, '', { result_source: '' }));
    await act(async () => {
      for (const [key, context] of page.shell.runtime.store.getSnapshot().contexts) {
        page.shell.runtime.store.setContext(key, {
          ...context,
          data: {
            semantic: { facts },
            sources: { work: { tool_reports: [] } },
          } as unknown as ProjectContext,
          revision: context.revision + 1,
        });
      }
    });
    await page.poll(original);
    expect(trigger()?.textContent).toContain('4 checks');
    expect(trigger()?.getAttribute('aria-expanded')).toBe('true');
    await page.go('#n=intent');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    await page.settle();
    expect(trigger()?.textContent).toContain('4 checks');
    expect(trigger()?.getAttribute('aria-expanded')).toBe('true');
    expect(document.querySelector('[data-check-run]')?.getAttribute('data-check-run')).toBe('c1');
    expect(
      [...document.querySelectorAll<HTMLElement>('[data-next-entry-id]')].map(
        (row) => row.dataset['nextEntryId'],
      ),
    ).toEqual(['c4', 'c3', 'c2', 'c1']);
  });

  it('reveals a consistent finding check and reaches it without expanding a fold', async () => {
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const page = mountDrift({
      facts: [1, 2, 3, 4, 5, 6, 7].map((n) =>
        check(`c${String(n)}`, 900 + n, n === 4 ? 'passed' : '', {
          result_source: n === 4 ? 'flag' : '',
        }),
      ),
      session: {
        annotation_at: 990,
        annotation_window_start: 100,
        annotation_reading_count: 1,
        annotation_assessment: {
          revision_read: 3,
          revision_read_at: 990,
          window_start: 100,
          read_at: 1000,
          evidence_through: 1000,
          goal_source: 'typed',
          stamp: 'model · m',
          scope: 'last-turn',
          scope_text: 'Read up to its last turn.',
          cutoff: 'Evidence read to its end.',
          coverage: {
            tail_truncated: false,
            tail_start: null,
            unlisted: 0,
            unread_checks: 0,
            goal_source: 'typed',
          },
          criteria: {
            goal: {
              result: 'consistent with the evidence read',
              cites: ['c4'],
              detail: '',
              clause: 'Ship the queue',
            },
            line_1: {
              result: 'not reached in this reading',
              cites: [],
              detail: '',
              clause: 'Tests pass',
            },
          },
        },
      },
    });
    await page.settle();
    await page.settle();
    expect(document.querySelectorAll('[data-check-run]')).toHaveLength(1);
    await jumpTo(document.querySelector('[data-next-cockpit-action="finding-jump"]'));
    const row = document.querySelector('[data-next-entry-id="c4"]');
    expect(row?.closest('[data-check-run]')).toBeNull();
    expect(document.querySelectorAll('[data-check-run]')).toHaveLength(2);
    expect(document.activeElement).toBe(row);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(row?.querySelector('[data-next-finding-entry]')).not.toBeNull();
  });

  it('reads an adopted /goal as a prompt source when placing the window anchor, as it does a prompt', async () => {
    const anchor = async (goalSource: string): Promise<string> => {
      const page = mountDrift({
        facts: [fact('p1', 900), fact('p2', 920)],
        session: {
          annotation_window_start: 800,
          annotation_at: 800,
          annotation_goal_saved_at: 800,
          annotation_goal_source: goalSource,
          annotation_reading_count: 0,
        },
      });
      await page.settle();
      await page.settle();
      const text = document.body.textContent ?? '';
      page.unmount();
      return text.includes('no longer reaches back to where your intent’s window opens')
        ? 'anchor'
        : '';
    };
    expect(await anchor('first-prompt')).toBe('anchor');
    expect(await anchor('session-goal')).toBe('anchor');
    expect(await anchor('typed')).toBe('');
  });
});
