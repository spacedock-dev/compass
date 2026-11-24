import { openSessionTechnicalTab } from '../../test/sessionTechnical';
import { act, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EXCERPTED_DRIFT, PROMPT_LIMITED_DRIFT } from '../../stories/driftCoverage.scenario';
import { liveMonitorFor } from '../intent/liveMonitor';
import {
  byAction,
  check,
  contextRoute,
  fact,
  driftBoard,
  json,
  jumpTo,
  LEASE_ROUTE,
  mountDrift,
  press,
  readingPosts,
  textOf,
} from './testing';

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
      result: 'departure',
      cites: ['c1'],
      detail: 'It stopped running the tests.',
      clause: 'Ship the queue',
    },
    line_1: {
      result: 'consistent with the evidence read',
      cites: ['c2'],
      detail: '',
      clause: 'Tests pass',
    },
  },
};

const FACTS = [
  check('c1', 500, 'failed', { result_source: 'failed flag', summary: 'pytest -q' }),
  check('c2', 600, 'passed'),
];

const stored = (extra: Record<string, unknown> = {}) => ({
  annotation_assessment: ASSESSMENT,
  annotation_window_start: 100,
  annotation_reading_count: 1,
  ...extra,
});

async function evidencePanel() {
  await openSessionTechnicalTab('Evidence');
  return within(screen.getByRole('tabpanel', { name: 'Evidence' }));
}

describe('the progress answer without a level', () => {
  it('explains when the session did not publish its saved goal', async () => {
    const board = driftBoard();
    const oldRow = Object.fromEntries(
      Object.entries(board.sessions[0] ?? {}).filter(
        ([key]) => !key.startsWith('annotation_') && !key.startsWith('first_prompt'),
      ),
    );
    const page = mountDrift({ payload: { sessions: [oldRow] } });
    await page.settle();
    expect(textOf('[data-next-progress-absence]')).toMatch(
      /^Can't tell.*Compass could not tell whether this session has a saved goal/,
    );
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
  });

  it('says not checked yet when the first prompt is a suggestion a check would save', async () => {
    // Check progress adopts the draft first, so a draft is a goal the board has yet to check: the list row
    // says Not checked yet for it, and this page agrees.
    const page = mountDrift({ store: { goal: '', lines: [], revision: 0 } });
    await page.settle();
    expect(screen.getByText(/Drafted from your first prompt · not saved/)).toBeVisible();
    expect(textOf('[data-next-progress-absence]')).toMatch(/^Not checked yet/);
    expect(textOf('[data-next-progress-absence]')).not.toMatch(/No goal yet/);
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
  });

  it('still says no goal yet when there is no draft to check', async () => {
    const board = driftBoard();
    const row = Object.fromEntries(
      Object.entries(board.sessions[0] ?? {}).filter(
        ([key]) =>
          !key.startsWith('first_prompt') &&
          !key.startsWith('annotation_line') &&
          key !== 'instruction',
      ),
    );
    const page = mountDrift({
      payload: { sessions: [{ ...row, annotation_goal: '', annotation_goal_why: 'None.' }] },
      store: { goal: '', lines: [], revision: 0 },
    });
    await page.settle();
    expect(textOf('[data-next-progress-absence]')).toMatch(/^No goal yet.*Give Compass a goal/);
  });

  it('explains a reading shape this version cannot interpret', async () => {
    const page = mountDrift({
      session: stored({ annotation_assessment: { ...ASSESSMENT, future_field: true } }),
      facts: FACTS,
    });
    await page.settle();
    expect(textOf('[data-next-progress-absence]')).toMatch(
      /^Can't tell.*This board cannot read the reading it was given/,
    );
    expect(document.querySelector('[data-next-drift-pill]')).toBeNull();
  });
});

describe('technical Evidence', () => {
  it('shows an empty history after a readable annotation lookup', async () => {
    const page = mountDrift();
    await page.settle();
    expect((await evidencePanel()).getByText('No stored check yet.')).toBeVisible();
  });

  it('shows the annotation store notice when the read was unavailable', async () => {
    const unreadable = 'Compass could not read compass-annotations.json. Try again later.';
    const page = mountDrift({ payload: { annotate_unreadable: unreadable } });
    await page.settle();
    const evidence = await evidencePanel();
    expect(evidence.getByText(unreadable)).toBeVisible();
    expect(evidence.queryByText('No stored check yet.')).toBeNull();
  });

  it('keeps the caveat when the goal changed after the stored check', async () => {
    const page = mountDrift({ session: stored(), store: { revision: 4 }, facts: FACTS });
    await page.settle();
    const evidence = await evidencePanel();
    expect(evidence.getByText('Your intent changed after this analysis.')).toBeVisible();
  });

  it('shows the marked state beside Undo', async () => {
    const page = mountDrift({ session: stored({ annotation_not_accurate: true }), facts: FACTS });
    await page.settle();
    const evidence = await evidencePanel();
    expect(
      evidence.getByText(/^Marked inaccurate\./).classList.contains('next-visually-hidden'),
    ).toBe(false);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeVisible();
  });

  it('counts both stored citations when only one is loaded', async () => {
    const page = mountDrift({
      session: stored({
        annotation_assessment: {
          ...ASSESSMENT,
          criteria: { goal: { ...ASSESSMENT.criteria.goal, cites: ['c1', 'older'] } },
        },
      }),
      facts: [FACTS[0]],
    });
    await page.settle();
    const evidence = await evidencePanel();
    expect(evidence.getByText(/2 entries cited/)).toBeVisible();
    expect(evidence.getAllByRole('link', { name: /^Show #.* in Activity log/ })).toHaveLength(1);
  });
});

describe('a stored reading', () => {
  it('offers the retry named by a failure when the earlier reading has no saved time', async () => {
    const failure = 'The progress check failed. Nothing was saved. Press Check progress again.';
    const page = mountDrift({
      session: stored({
        annotation_assessment: { ...ASSESSMENT, read_at: null },
        annotation_reading_withheld: failure,
      }),
      facts: FACTS,
    });
    await page.settle();
    expect(screen.getByText(failure, { exact: false })).toBeVisible();
    // The header's retry and its copy in Is it on track?, each with its cost beside it.
    const retries = screen.getAllByRole('button', { name: 'Check progress again' });
    expect(retries).toHaveLength(2);
    for (const retry of retries) {
      expect(retry).toBeVisible();
      expect(retry.nextElementSibling?.textContent).toBe('Uses AI');
    }
    expect(document.querySelector('[data-next-drift-stamp]')).toBeNull();
  });

  it("says the answer, then each line by the list's own number, and never a check mark", async () => {
    const page = mountDrift({ session: stored(), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const result = document.querySelector('[data-next-result]') as HTMLElement;
    expect(result).not.toBeNull();
    expect(result.textContent).not.toContain('Next Analyze prompt');
    // The answer is said once, in the verdict sentence under the card's heading.
    expect(textOf('[data-next-drift-verdict]')).toContain('1 departure');
    expect(document.querySelector('[data-next-result-heading]')).toBeNull();
    const goal = document.querySelector('[data-next-result-goal]') as HTMLElement;
    expect(goal.getAttribute('data-next-result-state')).toBe('departs');
    // The card's What is the cited entry, with its number; no Evidence fold restates it as a status.
    expect(goal.textContent).toContain('Failed check: pytest -q#1');
    expect(goal.textContent).not.toContain('Departs; evidence');
    const line = document.querySelector('.next-cockpit-result-lines li') as HTMLElement;
    expect(line.getAttribute('data-next-result-state')).toBe('consistent');
    expect(line.textContent).toContain('Consistent with #2');
    expect(result.textContent).not.toMatch(/[✓✔]/);
    // The numbers it names are rows on screen, and the one it cites is flagged.
    expect(document.querySelector('[data-next-entry="1"]')).not.toBeNull();
    expect(
      document.querySelector('[data-next-entry="1"] [data-next-entry-flag="cited"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('[data-next-entry="2"] [data-next-entry-flag="cited"]'),
    ).toBeNull();
    // The run control is the header's, from the first reading on.
    expect(byAction('reading-ask')?.textContent).toBe('Check progress again');
    expect(
      document.querySelector('.next-session-detail-header')?.contains(byAction('reading-ask')),
    ).toBe(true);
    expect(textOf('[data-next-technical-evidence]')).toContain('1 drift check requested');
    // Under the cap the budget is not mentioned anywhere.
    expect(result.textContent).not.toMatch(/left today/);
    expect(document.querySelector('[data-next-reading-cap]')).toBeNull();
  });

  it('withholds a verdict that cites nothing it can resolve, never softening it', async () => {
    const bad = {
      ...ASSESSMENT,
      criteria: {
        goal: { result: 'departure', cites: ['gone'], detail: 'x', clause: 'Ship the queue' },
      },
    };
    const page = mountDrift({
      session: stored({ annotation_assessment: bad }),
      facts: FACTS,
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    expect(textOf('[data-next-drift-verdict]')).toBe("Can't tell from what was read.");
    expect(document.querySelector('[data-next-result-goal]')?.textContent).toContain(
      'Nothing resolvable was cited',
    );
    expect(byAction('finding-jump')).toBeNull();
    expect(document.querySelector('[data-next-finding-entry]')).toBeNull();
  });

  it.each([
    ['cited nothing, which a withdrawn verdict leaves behind', []],
    ['cited a file write, which is not a check', ['w1']],
  ])('never says a check was cited when the reading %s', async (_name, cites) => {
    const withdrawn = {
      ...ASSESSMENT,
      criteria: {
        goal: {
          result: 'not verifiable from available evidence',
          cites,
          detail: '',
          clause: 'Ship the queue',
          why: 'check-does-not-show-it',
        },
      },
    };
    const page = mountDrift({
      session: stored({ annotation_assessment: withdrawn }),
      facts: [...FACTS, check('w1', 550, '', { subject: 'write', summary: 'src/queue.ts' })],
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    expect(textOf('[data-next-drift-verdict]')).toBe("Can't tell from what was read.");
    const why = document.querySelector('[data-next-result-goal] .next-cockpit-reading-why');
    expect(why?.textContent).toBe(
      'What it cited does not show this: a departure needs its latest run failing, and a consistent its latest run passing with no change after it, both after the words you saved.',
    );
    expect(document.body.textContent).not.toContain('The check it cited does not show this');
  });

  it('refuses a reading carrying a field this build does not know, and draws no verdict', async () => {
    const page = mountDrift({
      session: stored({ annotation_assessment: { ...ASSESSMENT, surprise: true } }),
      facts: FACTS,
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    expect(textOf('.next-cockpit-reading')).toContain('cannot read the reading it was given');
    expect(textOf('.next-cockpit-reading')).toContain('Unrecognised: surprise.');
    expect(document.querySelector('[data-next-result]')).toBeNull();
  });

  it('says a reading of earlier words is of earlier words, in the header beside Check progress again', async () => {
    const page = mountDrift({
      session: stored(),
      store: { revision: 4 },
      facts: FACTS,
    });
    await page.settle();
    await page.settle();
    const stale = document.querySelector('[data-next-result-stale]') as HTMLElement;
    expect(stale.getAttribute('data-next-result-stale')).toBe('intent');
    expect(stale.textContent).toBe('Out of date');
    const status = document.querySelector('[data-next-drift-status]') as HTMLElement;
    await openSessionTechnicalTab('Evidence');
    expect(textOf('[data-next-evidence-stale]')).toMatch(
      /This reading was made at .+ against an earlier version of your intent/,
    );
    expect(status.textContent).not.toMatch(/revision \d/i);
    expect(status.querySelector('[data-next-cockpit-action="reading-ask"]')?.textContent).toBe(
      'Check progress again',
    );
    // One press, drawn in the header and again in Is it on track?.
    expect(document.querySelectorAll('[data-next-cockpit-action="reading-ask"]')).toHaveLength(2);
  });

  it('says new work arrived after the reading read, and what kind', async () => {
    const page = mountDrift({
      session: stored(),
      facts: [
        ...FACTS,
        check('c3', 1200, 'passed'),
        fact('m1', 1250, { type: 'agent_message', by: 'agent' }),
      ],
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const stale = document.querySelector('[data-next-evidence-stale="work"]') as HTMLElement;
    expect(stale.textContent).toContain('New work since this analysis.');
    // One press, drawn in the header and again in Is it on track?.
    expect(document.querySelectorAll('[data-next-cockpit-action="reading-ask"]')).toHaveLength(2);
    expect(textOf('[data-next-result]')).toContain(
      '1 check, 1 message arrived since this analysis.',
    );
  });
});

describe('result focus', () => {
  it('receives focus from the running analysis when the current result replaces it', async () => {
    const job = { id: 'j1', phase: 'read', steps: [{ phase: 'read', text: 'Reading' }] };
    const page = mountDrift({ payload: { reading_jobs: { 'claude:s1': job } } });
    await page.settle();
    await page.settle();
    const title = document.querySelector<HTMLElement>('.next-cockpit-reading-job-title');
    expect(title).not.toBeNull();
    await act(async () => title?.focus());
    expect(document.activeElement).toBe(title);
    await page.poll({
      ...(page.state.data as object),
      reading_jobs: {},
      sessions: [{ ...(page.state.data as { sessions: object[] }).sessions[0], ...stored() }],
    });
    await page.settle();
    const answer = document.querySelector('[data-next-progress-answer]');
    expect(answer).not.toBeNull();
    expect(document.activeElement).toBe(answer);
  });
});

describe('a current result while model calls are paused', () => {
  it('offers Resume model calls, with the one re-run control inert', async () => {
    const page = mountDrift({
      session: stored(),
      facts: FACTS,
      payload: { reading: { consent: false, off: true, reason: 'model-calls-paused' } },
    });
    await page.settle();
    await page.settle();
    expect(document.querySelector('[data-next-progress-answer]')).not.toBeNull();
    /* By role, so a hidden popover node cannot stand in for the visible control. */
    const resume = screen.getByRole('button', { name: 'Resume AI use' });
    expect(resume.closest('[hidden]')).toBeNull();
    expect(resume.closest('[data-closed]')).toBeNull();
    expect(screen.queryAllByRole('button', { name: 'Resume AI use' })).toHaveLength(1);
    for (const control of document.querySelectorAll('[data-next-cockpit-action="reading-ask"]'))
      expect(control.getAttribute('aria-disabled')).toBe('true');
    // One press, drawn in the header and again in Is it on track?.
    expect(document.querySelectorAll('[data-next-cockpit-action="reading-ask"]')).toHaveLength(2);
  });
});

describe('a finding jump', () => {
  it('names each cited entry by its number, its constraint and the stored clause', async () => {
    const page = mountDrift({ session: stored(), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const jumps = [...document.querySelectorAll('[data-next-finding]')];
    expect(
      screen.queryByRole('link', {
        name: 'Show #1 in Activity log for Goal: Ship the queue',
      }),
    ).toBe(jumps[0]);
    expect(
      screen.queryByRole('link', {
        name: 'Show #2 in Activity log for Expected outcome line 1: Tests pass',
      }),
    ).toBe(jumps[1]);
  });

  it('tints the entries a finding cites so they stand apart from the rest of the list', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const page = mountDrift({ session: stored(), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const rows = () => [...document.querySelectorAll<HTMLElement>('[data-next-entry-id]')];
    expect(rows().some((row) => row.hasAttribute('data-next-cited'))).toBe(false);
    await jumpTo(document.querySelector('[data-next-technical-evidence] [data-next-finding]'));
    const cited = rows().filter((row) => row.hasAttribute('data-next-cited'));
    expect(cited.length).toBeGreaterThan(0);
    for (const row of cited) {
      expect(row.querySelector('[data-next-finding-entry]')).not.toBeNull();
      expect(row.className).toContain('var(--accent)');
    }
    for (const row of rows().filter((entry) => !cited.includes(entry))) {
      expect(row.className).not.toContain('var(--accent)');
    }
  });

  it('discards a selection when its citations vanish, even if they return in the same reading', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const page = mountDrift({ session: stored(), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    await jumpTo(document.querySelector('[data-next-technical-evidence] [data-next-finding]'));
    expect(document.querySelector('[data-next-finding-entry]')).not.toBeNull();
    const original = page.state.data as { sessions: object[] };
    await page.poll({
      ...original,
      sessions: [
        {
          ...original.sessions[0],
          annotation_assessment: {
            ...ASSESSMENT,
            criteria: {
              ...ASSESSMENT.criteria,
              goal: { ...ASSESSMENT.criteria.goal, cites: ['gone'] },
            },
          },
        },
      ],
    });
    expect(document.querySelector('[data-next-finding-entry]')).toBeNull();
    await page.poll(original);
    expect(document.querySelector('[data-next-finding-entry]')).toBeNull();
  });

  it('discards a selection when the session changes and does not restore it on return', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const page = mountDrift({ session: stored(), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const original = page.state.data as { sessions: object[] };
    await page.poll({
      ...original,
      sessions: [original.sessions[0], { ...original.sessions[0], sid: 's2' }],
    });
    await jumpTo(document.querySelector('[data-next-technical-evidence] [data-next-finding]'));
    expect(document.querySelector('[data-next-finding-entry]')).not.toBeNull();
    await page.go('#n=session:alpha%2Fapp:claude:s2');
    expect(document.querySelector('[data-next-finding-entry]')).toBeNull();
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(document.querySelector('[data-next-finding-entry]')).toBeNull();
  });

  it('a reader reaches a consistent finding’s already listed older message without a departure tag', async () => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const page = mountDrift({
      session: stored({
        annotation_assessment: {
          ...ASSESSMENT,
          criteria: {
            ...ASSESSMENT.criteria,
            goal: {
              result: 'consistent with the evidence read',
              cites: ['old'],
              clause: 'Ship the queue',
            },
          },
        },
      }),
      facts: [
        fact('old', 500, { type: 'agent_message', by: 'agent' }),
        check('c2', 600, 'passed'),
        ...Array.from({ length: 12 }, (_, i) =>
          fact(`a${i}`, 700 + i, { type: 'agent_message', by: 'agent' }),
        ),
      ],
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    expect(document.querySelector('[data-next-entry-id="old"]')).not.toBeNull();
    expect(
      document.querySelector('[data-next-entry-id="old"] [data-next-finding-entry]'),
    ).toBeNull();
    await jumpTo(document.querySelector('[data-next-technical-evidence] [data-next-finding]'));
    const row = document.querySelector('[data-next-entry-id="old"]');
    expect(row?.textContent).toContain('Cited for “Ship the queue” · #1');
    expect(row?.querySelector('[data-next-entry-flag="cited"]')).toBeNull();
    expect(document.activeElement).toBe(row);
  });

  it('marks its entries with the stored words and focuses the first without a request', async () => {
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const page = mountDrift({ session: stored(), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const requests = [...page.state.requests];
    await jumpTo(document.querySelector('[data-next-technical-evidence] [data-next-finding]'));
    const entry = document.querySelector('[data-next-entry-id="c1"]');
    expect(entry?.textContent).toContain('Cited for “It stopped running the tests.” · #1');
    expect(document.activeElement).toBe(entry);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll).toHaveBeenCalledWith({ behavior: 'instant', block: 'center' });
    expect(page.state.requests).toEqual(requests);
    expect(
      document.querySelector('[data-next-entry-id="c2"] [data-next-finding-entry]'),
    ).toBeNull();
  });
});

describe('a goal stated with /goal', () => {
  const goalCommand = {
    ...ASSESSMENT,
    goal_source: 'session-goal',
    goal_source_at: 980,
  };

  it('says it came from /goal, never from a prompt', async () => {
    const page = mountDrift({
      session: stored({
        annotation_assessment: goalCommand,
        annotation_goal_source: 'session-goal',
      }),
      facts: FACTS,
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const read = textOf('[data-next-read]');
    expect(read).toContain('from /goal');
    expect(read).not.toContain('drafted from your prompt');
  });
});

describe('a refusal of a goal too vague to analyze', () => {
  const refused = {
    ...ASSESSMENT,
    criteria: {
      goal: {
        result: 'goal too vague to analyze against',
        cites: [],
        detail: '',
        clause: 'testing',
      },
    },
  };

  it('offers no mark of inaccuracy, because it sets no level and offers no Steer back', async () => {
    const page = mountDrift({ session: stored({ annotation_assessment: refused }), facts: FACTS });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    expect(document.querySelector('[data-next-result]')).not.toBeNull();
    expect(byAction('not-accurate')).toBeFalsy();
    expect(document.body.textContent).not.toContain('This reading looks wrong');
  });
});

const foot = () => document.querySelector('[data-next-result-mark]') as HTMLElement | null;

describe('Not accurate', () => {
  it('derives its mark from the payload and never from the press', async () => {
    const page = mountDrift({
      session: stored(),
      facts: FACTS,
      routes: {
        '/api/annotate': () => json({ ok: true, outcome: 'untrusted', persisted: false }),
      },
    });
    await page.settle();
    await page.settle();
    const mark = byAction('not-accurate') as HTMLElement;
    expect(mark.textContent).toBe('This reading looks wrong');
    // Before the press, the reader is told what it does.
    expect(foot()?.getAttribute('data-next-result-mark')).toBe('unmarked');
    expect(foot()?.textContent).toContain(
      'Sets this check aside and turns off Steer back for it. Nothing is sent or re-run.',
    );
    await press(mark);
    await page.settle();
    const posts = page.state.requests.filter(
      (r) => r.method === 'POST' && r.path === '/api/annotate',
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toMatchObject({
      harness: 'claude',
      sid: 's1',
      not_accurate: true,
      read_at: 1000,
    });
    // The store did not take it: still unmarked, and said so beside the control.
    expect(foot()?.getAttribute('data-next-result-mark')).toBe('unmarked');
    expect(foot()?.textContent).toContain('Your mark was not saved. Try again.');
    // Marked on the board, it draws marked: what changed is said beside the control, the control undoes it,
    // and the level's own slot says why it is gone.
    await page.poll({
      ...(page.state.data as object),
      generated: 1100,
      sessions: [
        {
          ...(page.state.data as { sessions: object[] }).sessions[0],
          annotation_not_accurate: true,
        },
      ],
    });
    expect(document.querySelector('[data-next-drift-marked]')).not.toBeNull();
    expect(byAction('not-accurate')?.textContent).toBe('Undo');
    // One message, where the level was, with Undo and Check progress again beside it; the foot says nothing more.
    expect(textOf('[data-next-drift-marked] [role="status"]')).toBe(
      'Marked inaccurate. This check is set aside and no longer offers Steer back.',
    );
    expect(foot()?.textContent).toBe('');
    expect(
      document.querySelector('[data-next-drift-status] [data-next-cockpit-action="reading-ask"]')
        ?.textContent,
    ).toBe('Check progress again');
    expect(document.querySelector('[data-next-drift-level]')).toBeNull();
    await openSessionTechnicalTab('Evidence');
    expect(document.querySelector('[data-next-disowned]')).not.toBeNull();
    // Undo posts the mark back off.
    await press(byAction('not-accurate') as HTMLElement);
    await page.settle();
    const undo = page.state.requests.filter(
      (r) => r.method === 'POST' && r.path === '/api/annotate',
    );
    expect(undo.at(-1)?.body).toMatchObject({ not_accurate: false, read_at: 1000 });
  });
});

describe('A marked reading with the Live monitor on', () => {
  const LIVE = {
    harness: 'claude',
    sid: 's1',
    revision: 3,
    computed_at: 990,
    level: 'medium',
    reasons: ['pass-then-write'],
    cites: [],
  };

  it.each([
    ['a live level row', [LIVE]],
    ['no live level row', []],
  ])(
    'still says it is marked and keeps Undo and Check progress again with %s',
    async (_name, rows) => {
      const page = mountDrift({
        session: stored({ annotation_not_accurate: true }),
        facts: FACTS,
        routes: {
          '/api/project-context': contextRoute(FACTS, { live_levels: rows }),
          '/api/live-monitor': LEASE_ROUTE,
        },
      });
      await page.settle();
      await page.settle();
      await act(async () => {
        liveMonitorFor(page.shell).update('claude:s1', { wanted: true });
      });
      await page.settle();
      expect(document.querySelector('[data-next-drift-marked]')).not.toBeNull();
      expect(byAction('not-accurate')?.textContent).toBe('Undo');
      expect(
        document.querySelector('[data-next-drift-status] [data-next-cockpit-action="reading-ask"]')
          ?.textContent,
      ).toBe('Check progress again');
      await openSessionTechnicalTab('Evidence');
      expect(document.querySelector('[data-next-disowned]')).not.toBeNull();
    },
  );
});

describe('What the check read', () => {
  it.each([
    [
      'excerpted messages',
      EXCERPTED_DRIFT,
      'Read all 2 entries',
      '1 message was read only in part.',
    ],
    [
      'prompt exhaustion',
      PROMPT_LIMITED_DRIFT,
      'Read 1 of the 4 entries',
      '3 checks had no room in the prompt.',
    ],
  ] as const)(
    'keeps %s explicit even without a source-tail gap',
    async (_name, evidence, count, omission) => {
      const page = mountDrift({
        session: stored({ annotation_assessment: { ...ASSESSMENT, ...evidence } }),
        facts: FACTS,
      });
      await page.settle();
      await page.settle();
      await openSessionTechnicalTab('Evidence');
      const session = textOf('[data-next-read-section="session"]');
      expect(session).toContain(count);
      expect(session).toContain(omission);
      expect(session).not.toMatch(/tail.*truncated|outside it|start time was not recorded/i);
      if (evidence.coverage.unlisted) {
        expect(session).toContain('2 passes or writes in the window were left unlisted');
        expect(textOf('[data-next-reading-coverage]')).toContain(
          '2 passes or writes in the window were not listed.',
        );
      } else {
        expect(session).not.toContain('left unlisted');
      }
      expect(readingPosts(page)).toEqual([]);
    },
  );

  it('groups the model, the intent, the session and what is never read under headings', async () => {
    const page = mountDrift({
      session: stored({
        annotation_assessment: {
          ...ASSESSMENT,
          scope: 'final',
          stamp: 'claude-sonnet-5-5 · read at 09:38',
          cutoff:
            'Read all 4 entries after your intent: 1 from you, 3 messages from the agent. The oldest is from about 13h ago.',
        },
      }),
      facts: FACTS,
    });
    await page.settle();
    await openSessionTechnicalTab('Evidence');
    await page.settle();
    const read = document.querySelector('[data-next-read]') as HTMLElement;
    expect(read).not.toBeNull();
    const section = (name: string) =>
      read.querySelector(`[data-next-read-section="${name}"]`) as HTMLElement;
    // The model alone: the read time is the card header's "Analysis last run", said once.
    expect(section('model').textContent).toContain('claude-sonnet-5-5');
    expect(section('model').textContent).not.toMatch(/read at|\d\d:\d\d/);
    const intent = section('intent');
    expect(intent.querySelector('h4')?.textContent).toBe('Your intent');
    expect(intent.textContent).toMatch(/typed .+ ago/);
    expect(intent.textContent).not.toContain('Version');
    expect([...intent.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
      'Goal “Ship the queue”',
      'Expected outcome “Tests pass”',
    ]);
    expect([...section('session').querySelectorAll('li')].map((li) => li.textContent)).toEqual([
      'Everything up to the session’s end.',
      'Read all 4 entries after your intent: 1 from you, 3 messages from the agent.',
      'The oldest is from about 13h ago.',
      'How many other commands ran beside the entries read was not recorded for this reading.',
    ]);
    expect(section('not-read').textContent).toContain('Files, diffs, test results');
    // The retired wording is gone.
    for (const retired of [
      'A reading is one model pass',
      'What it reads is the evidence on this page',
      'Baseline from your prompt',
      'GOAL FROM YOUR PROMPT',
      'Revision 3',
    ]) {
      expect(read.textContent).not.toContain(retired);
    }
  });
});
