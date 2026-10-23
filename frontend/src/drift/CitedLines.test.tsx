import { describe, expect, it, vi } from 'vitest';
import { check, fact, jumpTo, mountDrift } from './testing';

/* Each cited entry is one line in its own words with its number, on a claim row and on a departure card
   (owner, 2026-10-23: the citations are the source), and neither carries an Evidence or Source fold. */

const ASSESSMENT = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  scope_text: 'Read up to its last turn.',
  stamp: 'model · m',
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
      cites: ['m1'],
      detail: '',
      clause: 'Ship the queue',
    },
    line_1: {
      result: 'departure',
      cites: ['m1', 'c1'],
      detail: 'pytest failed after the agent said it was done.',
      clause: 'Tests pass',
    },
    claims: {
      result: 'departure',
      cites: ['m1', 'c1'],
      detail: 'pytest failed after the claim.',
      clause: '',
    },
  },
};

const FACTS = [
  fact('p1', 400, { summary: 'Ship the queue with passing tests' }),
  fact('m1', 500, {
    type: 'agent_message',
    by: 'agent',
    summary: 'The queue is done and the tests pass.',
  }),
  check('c1', 600, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
];

const mount = async () => {
  const page = mountDrift({
    session: {
      annotation_assessment: ASSESSMENT,
      annotation_window_start: 100,
      annotation_reading_count: 1,
    },
    facts: FACTS,
  });
  await page.settle();
  await page.settle();
  return page;
};

const lines = (root: Element) =>
  [...root.querySelectorAll('[data-next-cited-entries] li, p[data-next-cited-entries]')].map(
    (node) => (node.textContent ?? '').replace(/\s+/g, ' ').trim(),
  );

describe('the cited entries on a claim row and a departure card', () => {
  it('draws each cited entry on a claim row as its own words and its number', async () => {
    await mount();
    const claim = document.querySelector('[data-next-result-claims]') as HTMLElement;
    const found = lines(claim);
    expect(found).toHaveLength(2);
    expect(found[0]).toMatch(/^Agent said: “The queue is done and the tests pass\.” ?\[\d+\]/);
    expect(found[1]).toMatch(/^Failed check: pytest -q ?\[\d+\]/);
  });

  it('draws one line per cited entry on a departure card, in the same form as the claims row', async () => {
    await mount();
    const card = document.querySelector('[data-next-departure="line_1"]') as HTMLElement;
    const found = lines(card);
    expect(found).toHaveLength(2);
    expect(found.join(' ')).toContain('pytest -q');
    expect(found.join(' ')).toContain('Agent said: “The queue is done and the tests pass.”');
    expect(found.join(' ')).not.toContain('At ');
  });

  it('draws a quiet goal row the same way, with no kind-only label', async () => {
    await mount();
    const goal = document.querySelector('[data-next-result-goal]') as HTMLElement;
    const found = lines(goal);
    expect(found).toHaveLength(1);
    expect(found[0]).toMatch(/^Agent said: “The queue is done and the tests pass\.” ?\[\d+\]/);
    expect(goal.textContent).not.toContain('Agent message');
  });

  it('has no Evidence or Source fold anywhere on the result', async () => {
    await mount();
    for (const node of [
      document.querySelector('[data-next-result-claims]'),
      document.querySelector('[data-next-result-goal]'),
      ...document.querySelectorAll('[data-next-departure]'),
      document.querySelector('[data-next-result]'),
    ]) {
      const names = [...(node as HTMLElement).querySelectorAll('button')].map(
        (button) => button.textContent ?? '',
      );
      expect(names.filter((name) => /^(Evidence|Source)/.test(name.trim()))).toEqual([]);
      expect((node as HTMLElement).textContent).not.toContain('Evidence recorded at');
      expect((node as HTMLElement).textContent).not.toContain('timestamped');
    }
  });

  it('keeps pressing a number opening Full activity on that entry', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    await mount();
    const claim = document.querySelector('[data-next-result-claims]') as HTMLElement;
    const second = claim.querySelectorAll('[data-next-cite]')[1] as HTMLElement;
    await jumpTo(second);
    const cited = [...document.querySelectorAll('[data-next-entry-id][data-next-cited]')];
    expect(cited.map((row) => row.getAttribute('data-next-entry-id'))).toContain('c1');
  });
});
