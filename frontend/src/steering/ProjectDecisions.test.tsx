import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProjectDecisions } from './ProjectDecisions';
import { json, mountPanels, type MountOptions } from './testing';

/* The Decisions tab: the one-line account of what became of the recorded decisions, then the shared timeline
   under its filter. The summary reads the same context the timeline draws. */
const gate = (id: string, state: string, at: number) => ({
  fact_id: id,
  at,
  type: 'gate_decision',
  source_kind: 'gate',
  summary: `gate ${id}`,
  scope: 'project',
  by: 'person:captain',
  decision: 'approve',
  stage: 'review',
  application_state: state,
  work_item_id: 'workflow:w',
  evidence: { source: 'entity gate', confidence: 'exact' },
});
const SEMANTIC = {
  facts: [
    gate('g1', 'pending', 100),
    gate('g2', 'consumed', 101),
    gate('g3', 'consumed', 102),
    gate('g4', 'bogus', 103),
  ],
  work_items: [{ work_item_id: 'workflow:w', label: 'wf', kind: 'workflow_item' }],
  relations: [],
  projections: {},
};
const board = {
  generated: 1000,
  sessions: [
    {
      harness: 'claude',
      sid: 's1',
      project: 'alpha',
      state: 'working',
      subagents: [{ name: 'child', active: true }],
    },
    { harness: 'codex', sid: 's2', project: 'alpha', state: 'idle' },
  ],
};
const mount = (focus: { harness: string; sid: string } | null, options: MountOptions = {}) =>
  mountPanels(<ProjectDecisions project="alpha" projectKey="alpha" focus={focus} />, {
    data: board,
    routes: { '/api/project-context': () => json({ semantic: SEMANTIC }) },
    ...options,
  });

describe('the Decisions tab', () => {
  it('says what became of the decisions, then draws them under the recorded-decisions heading', async () => {
    const page = mount(null);
    await page.settle();
    expect(document.querySelector('[data-next-cockpit-decision-summary]')?.textContent).toBe(
      'Decision application · pending 1 · unknown 1 · consumed/applied 2',
    );
    expect(screen.getByText('Recorded decisions')).toBeInTheDocument();
    expect(document.querySelectorAll('.pc-graph-row').length).toBeGreaterThan(0);
  });

  it('says nothing about decisions when the context records none', async () => {
    const page = mount(null, {
      routes: { '/api/project-context': () => json({ semantic: { facts: [], work_items: [] } }) },
    });
    await page.settle();
    expect(document.querySelector('[data-next-cockpit-decision-summary]')).toBeNull();
  });

  it('reads the focused session’s own context when one is selected', async () => {
    const page = mount(
      { harness: 'claude', sid: 's1' },
      {
        routes: {
          '/api/project-context': (request) =>
            json({
              semantic: request.url.includes('session=')
                ? { facts: [gate('only', 'superseded', 1)] }
                : SEMANTIC,
            }),
        },
      },
    );
    await page.settle();
    expect(document.querySelector('[data-next-cockpit-decision-summary]')?.textContent).toBe(
      'Decision application · superseded 1',
    );
  });

  it('sends nothing: reads only', async () => {
    const page = mount(null);
    await page.settle();
    expect(page.allPosts()).toEqual([]);
    expect(page.state.requests.every((request) => request.method === 'GET')).toBe(true);
  });
});
