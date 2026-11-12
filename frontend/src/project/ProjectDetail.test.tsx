import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { blockedBackend } from '../../test/storage_backends';
import { memoKey, STORAGE_KEYS } from '../storage';
import { scenarios } from './generate.test.helper';
import { mountProject } from './testing';

/* The project page behind the real shell and a scripted backend: what the strip says, what a press does
   and what a mount, a poll, a reconnect and StrictMode never do. The legacy page is the oracle for every
   sentence in `ProjectDetail.differential.test.tsx`; these are the behaviours a text comparison cannot see. */

const [CALM, ENDED, PLAN, COURSE, WAITING] = scenarios();
const hash = (project: string, tail = '') => `#n=project:${encodeURIComponent(project)}${tail}`;

function open(
  scenario: NonNullable<typeof CALM>,
  tail = '',
  options: Parameters<typeof mountProject>[0] = {},
) {
  const project = String((scenario.board['sessions'] as { project: string }[])[0]?.project);
  return mountProject({
    hash: hash(project, tail),
    data: scenario.board,
    contexts: scenario.context ? { [`${project}\n`]: scenario.context } : {},
    ...options,
  });
}

describe('a project page asks for nothing it was not pressed for', () => {
  it('sends no POST and writes no clipboard on mount, under StrictMode, on a poll or on a tab change', async () => {
    const page = open(WAITING as never);
    await page.settle();
    fireEvent.click(screen.getByRole('tab', { name: /Course/ }));
    await page.settle();
    fireEvent.click(screen.getByRole('tab', { name: /Decisions/ }));
    await page.poll(WAITING?.board);
    expect(page.posts()).toEqual([]);
    expect(page.written).toEqual([]);
  });

  it('reads the project context once for a board, and again only when the board moves on', async () => {
    const page = open(CALM as never);
    await page.settle();
    expect(page.contextReads()).toHaveLength(1);
    await page.poll(CALM?.board);
    // The same board again carries the same clock: nothing newer to ask about.
    expect(page.contextReads()).toHaveLength(1);
    await page.poll({ ...(CALM?.board as object), generated: 1010 });
    expect(page.contextReads()).toHaveLength(2);
  });

  it('makes the focused read only for the tabs that draw it, and never for an unfocused session', async () => {
    const project = 'wait/app';
    const focused = hash(project, ':claude%3Aa:course');
    const page = mountProject({
      hash: focused,
      data: WAITING?.board,
      contexts: { [`${project}\n`]: WAITING?.context, [`${project}\nclaude:a`]: WAITING?.context },
    });
    await page.settle();
    expect(page.contextReads().map((read) => decodeURIComponent(read.url))).toEqual([
      '/api/project-context?project=wait/app',
      '/api/project-context?project=wait/app&session=claude:a',
    ]);
  });
});

describe('a focused session on the Now tab', () => {
  it('reads only the project’s own context: the focused read belongs to the tabs that draw it', async () => {
    const project = 'wait/app';
    const page = mountProject({
      hash: hash(project, ':claude%3Aa'),
      data: WAITING?.board,
      contexts: { [`${project}\n`]: WAITING?.context, [`${project}\nclaude:a`]: WAITING?.context },
    });
    await page.settle();
    expect(page.contextReads().map((read) => decodeURIComponent(read.url))).toEqual([
      '/api/project-context?project=wait/app',
    ]);
  });
});

describe('the recovery strip', () => {
  it('names the task source in plain words and preserves the published instruction', async () => {
    const scenario = WAITING as NonNullable<typeof WAITING>;
    const sessions = (scenario.board['sessions'] as Record<string, unknown>[]).map((row) => ({
      ...row,
      instruction: { label: 'asked', text: 'Review the assignment source', at: 900 },
    }));
    const page = open({ ...scenario, board: { ...scenario.board, sessions } });
    await page.settle();
    const strip = screen.getByLabelText('Recovery summary');
    expect(within(strip).getByText('Evidence · task source')).toBeInTheDocument();
    expect(within(strip).getByText('Review the assignment source')).toBeInTheDocument();
    expect(within(strip).getAllByText(/claude · latest instruction/).length).toBeGreaterThan(0);
  });

  it('calls missing child evidence a task while keeping published assignments intact', async () => {
    const scenario = CALM as NonNullable<typeof CALM>;
    const sessions = (scenario.board['sessions'] as Record<string, unknown>[]).map((row) => ({
      ...row,
      state: 'working',
      subagent_hierarchy: [
        { name: 'missing', active: true },
        { name: 'published', active: true, assignment: 'Review the assignment source' },
      ],
    }));
    const page = open({ ...scenario, board: { ...scenario.board, sessions } });
    await page.settle();
    const strip = screen.getByLabelText('Recovery summary');
    expect(within(strip).getAllByText('task unavailable').length).toBeGreaterThan(0);
    expect(strip.textContent).toContain('task source unavailable');
    expect(within(strip).getAllByText('Review the assignment source').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('tab', { name: /Decisions/ }));
    await page.settle();
    const contributors = document.querySelector('.pc-unbound-context');
    expect(contributors?.textContent).toContain('task unavailable');
    expect(contributors?.textContent).toContain('task source unavailable');
    expect(contributors?.textContent).toContain('Review the assignment source');
  });

  it('names what the captain has to do, with its source, before anything is concluded', async () => {
    const page = open(WAITING as never);
    await page.settle();
    const strip = screen.getByLabelText('Recovery summary');
    expect(within(strip).getByText('NEEDS YOU')).toBeTruthy();
    expect(within(strip).getByText('ANSWER · Approve the plan?')).toBeTruthy();
    expect(within(strip).getByText('WAITING ON YOU')).toBeTruthy();
    // The exact request, the raise and the copy of the re-entry command, each on its own press.
    expect(within(strip).getByText('Copy command')).toBeTruthy();
  });

  it('says a read that never arrived is unavailable, not that nothing needs the captain', async () => {
    const page = mountProject({ hash: hash('calm/app'), data: CALM?.board, contexts: {} });
    await page.settle();
    const strip = screen.getByLabelText('Recovery summary');
    expect(
      within(strip).getAllByText(/Attention unavailable · project context request failed/).length,
    ).toBeGreaterThan(0);
    expect(within(strip).queryByText('You are not needed')).toBeNull();
  });

  it('draws a project with nothing running and nothing asked as idle, and says why', async () => {
    const page = open(ENDED as never);
    await page.settle();
    const strip = screen.getByLabelText('Recovery summary');
    expect(within(strip).getByText('CONTINUES · Continue the current task')).toBeTruthy();
    expect(within(strip).getByText('No execution observed · You are not needed')).toBeTruthy();
  });
});

describe('the Copy briefing control', () => {
  it('writes the briefing once per press, from the rows the strip draws, and never before', async () => {
    const page = open(WAITING as never);
    await page.settle();
    expect(page.written).toEqual([]);
    fireEvent.click(screen.getByLabelText('More'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy briefing' }));
      await page.settle();
    });
    expect(page.written).toHaveLength(1);
    expect(page.written[0]).toMatch(/^Compass recovery briefing\nProject: app\nScope: Project\n/);
    expect(page.written[0]).toContain('Your attention: Authorize the dispatch?');
    expect(screen.getByRole('button', { name: 'Copied' })).toBeTruthy();
  });

  it('includes the reader’s own notes, marked as browser-local, and nothing the agents did not publish', async () => {
    const key = memoKey('wait/app', null, 'outcome');
    const page = open(WAITING as never, '', { storage: { [key]: 'Land the queue' } });
    await page.settle();
    fireEvent.click(screen.getByLabelText('More'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy briefing' }));
      await page.settle();
    });
    expect(page.written[0]).toContain('Outcome (browser-local): Land the queue');
    expect(page.written[0]).not.toContain('Focus (browser-local)');
  });
});

describe('the human context notes', () => {
  /* A project whose context read failed: no task is known and the attention scan is unavailable, so the
     briefing is incomplete and the strip itself carries the offer. */
  async function opened(options: Parameters<typeof mountProject>[0] = {}) {
    const page = mountProject({
      hash: hash('calm/app'),
      data: CALM?.board,
      contexts: {},
      ...options,
    });
    await page.settle();
    return page;
  }

  it('offers the notes in the strip where the briefing is incomplete, and in the menu where it is complete', async () => {
    const page = await opened();
    expect(screen.getByText('+ Add human context · this browser')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('More'));
    expect(screen.queryByRole('button', { name: 'Add human context' })).toBeNull();
    page.unmount();
    // A known task and a finished scan: the strip is quiet and the menu carries the offer instead.
    const complete = open(WAITING as never);
    await complete.settle();
    expect(screen.queryByText('+ Add human context · this browser')).toBeNull();
    fireEvent.click(screen.getByLabelText('More'));
    expect(screen.getByRole('button', { name: 'Add human context' })).toBeTruthy();
  });

  it('saves on every input to the released key, shows both notes, and reads them back after a reload', async () => {
    const page = await opened();
    fireEvent.click(screen.getByText('+ Add human context · this browser'));
    await page.settle();
    const box = screen.getByPlaceholderText(
      'What result should this scope achieve?',
    ) as HTMLTextAreaElement;
    expect(document.activeElement).toBe(box);
    fireEvent.input(box, { target: { value: 'Land the queue' } });
    const key = memoKey('calm/app', null, 'outcome');
    expect(page.backend.data.get(key)).toBe('Land the queue');
    expect(screen.getByText('Saved in this browser')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await page.settle();
    expect(screen.getByText('OPTIONAL HUMAN NOTE · THIS BROWSER')).toBeTruthy();
    expect(screen.getByText('Land the queue')).toBeTruthy();
    expect(screen.getAllByText('Not set')).toHaveLength(1);
    page.unmount();
    // A reload: a new document over the same storage.
    const again = await opened({ storageBackend: page.backend });
    expect(screen.getByText('Land the queue')).toBeTruthy();
    void again;
  });

  it('keeps the words in the tab and says storage is unavailable when the browser refuses it', async () => {
    const page = await opened({ storageBackend: blockedBackend() as never });
    fireEvent.click(screen.getByText('+ Add human context · this browser'));
    await page.settle();
    const box = screen.getByPlaceholderText(
      'What result should this scope achieve?',
    ) as HTMLTextAreaElement;
    fireEvent.input(box, { target: { value: 'kept anyway' } });
    expect(screen.getByText('Browser storage unavailable')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await page.settle();
    expect(screen.getByText('kept anyway')).toBeTruthy();
  });

  it('keeps a long memo and refuses an over-limit paste without replacing its saved words', async () => {
    const page = await opened();
    fireEvent.click(screen.getByText('+ Add human context · this browser'));
    await page.settle();
    const box = screen.getByPlaceholderText(
      'What result should this scope achieve?',
    ) as HTMLTextAreaElement;
    fireEvent.input(box, { target: { value: 'x'.repeat(700) } });
    expect(box.value).toHaveLength(700);
    expect(page.backend.data.get(memoKey('calm/app', null, 'outcome'))).toHaveLength(700);
    fireEvent.input(box, { target: { value: 'x'.repeat(2100) } });
    expect(box.value).toHaveLength(2100);
    expect(page.backend.data.get(memoKey('calm/app', null, 'outcome'))).toHaveLength(700);
    expect(screen.getByText('2100 characters; the limit is 2000.')).toBeVisible();
    expect((screen.getByRole('button', { name: 'Done' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('is not offered at a focused session, where the strip draws no note', async () => {
    const page = mountProject({
      hash: hash('wait/app', ':claude%3Aa'),
      data: WAITING?.board,
      contexts: { 'wait/app\n': WAITING?.context },
    });
    await page.settle();
    expect(screen.queryByText('+ Add human context · this browser')).toBeNull();
    expect(screen.queryByText('OPTIONAL HUMAN NOTE · THIS BROWSER')).toBeNull();
  });
});

describe('the scopes', () => {
  it('draws the project root and each exact session as different scopes, and keeps the tab on a change', async () => {
    const page = open(WAITING as never, ':course');
    await page.settle();
    const tree = screen.getByRole('navigation', { name: 'Project scope' });
    const links = within(tree).getAllByRole('link');
    expect(links.map((link) => link.getAttribute('data-scope-kind'))).toEqual([
      'project',
      'session',
      'session',
    ]);
    expect(links[0]?.getAttribute('aria-current')).toBe('page');
    expect(links[1]?.getAttribute('href')).toBe('#n=project:wait%2Fapp:claude%3Aa:course');
    fireEvent.click(links[1] as HTMLElement);
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({
      view: 'project',
      focus: 'claude:a',
      tab: 'course',
    });
    const focused = within(screen.getByRole('navigation', { name: 'Project scope' })).getAllByRole(
      'link',
    );
    expect(focused[1]?.getAttribute('aria-current')).toBe('page');
    expect(focused[0]?.hasAttribute('aria-current')).toBe(false);
    expect(
      screen.getAllByText(/Viewing session · Claude Code · needs_input/).length,
    ).toBeGreaterThan(0);
  });
});

describe('Now', () => {
  it('lists the plan with its entities and flags the one that stopped moving', async () => {
    const page = open(PLAN as never);
    await page.settle();
    fireEvent.click(screen.getByText('Show project plan'));
    const alpha = document.querySelector('[data-next-plan-entity="alpha"]') as HTMLElement;
    expect(alpha.textContent).toContain('stalled 11m');
    const beta = document.querySelector('[data-next-plan-entity="beta"]') as HTMLElement;
    expect(beta.getAttribute('data-next-live')).toBe('false');
    expect(screen.getByText('1 entity unhealthy —')).toBeTruthy();
    expect(screen.getByText('estimate withheld')).toBeTruthy();
  });
});

describe('Course', () => {
  it('lists derived and exact episodes with their own badges, and never calls a review a verified result', async () => {
    const page = open(COURSE as never, ':course');
    await page.settle();
    const badges = [
      ...document.querySelectorAll('.next-course-episode > header > span:last-child'),
    ].map((node) => node.textContent);
    expect(badges).toContain('DERIVED COURSE CHANGE');
    expect(badges).toContain('EXACT RESULT');
    expect(badges).toContain('EXACT DECISION');
    expect(badges).toContain('EXACT STATE CHANGE');
    const review = document.querySelector(
      '[data-epistemic-kind="derived-course-change"]',
    ) as HTMLElement;
    expect(review.textContent).toContain('drop the cache');
    expect(review.textContent).not.toMatch(/verified|success/i);
    // Ten state changes and three more episodes: the oldest gather behind a disclosure with their count.
    expect(screen.getByText(/\d+ Earlier/)).toBeTruthy();
    expect(screen.getByText('Other directions (1)')).toBeTruthy();
  });

  it('says it is loading while the read is in flight and unavailable once it failed, never "no changes"', async () => {
    const held = mountProject({
      hash: hash('course/app', ':course'),
      data: COURSE?.board,
      contexts: { 'course/app\n': COURSE?.context },
    });
    held.state.held.add('course/app\n');
    await held.settle();
    expect(screen.getByText('Loading course evidence…')).toBeTruthy();
    held.unmount();
    const failed = mountProject({
      hash: hash('course/app', ':course'),
      data: COURSE?.board,
      contexts: {},
    });
    await failed.settle();
    expect(screen.getByText('Course evidence unavailable.')).toBeTruthy();
  });

  it('counts a state change only from the evidence, and a project with none says how far back it looked', async () => {
    const page = open(CALM as never, ':course');
    await page.settle();
    expect(screen.getByText('No state changes observed since this tab opened.')).toBeTruthy();
    expect(screen.getByText(/0 of 0 unattended · since this tab opened/)).toBeTruthy();
  });
});

describe('the workstream panel', () => {
  it('collapses and expands, keeps the choice for the next load, and writes the released key as 1 or 0', async () => {
    const page = open(CALM as never, ':course');
    await page.settle();
    const toggle = screen.getByRole('button', { name: /OBSERVED STATE CHANGES/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(toggle);
    expect(page.backend.data.get(STORAGE_KEYS.workstreamCollapsed)).toBe('1');
    expect(screen.queryByText('No state changes observed since this tab opened.')).toBeNull();
    page.unmount();
    const again = open(CALM as never, ':course', { storageBackend: page.backend });
    await again.settle();
    expect(
      screen.getByRole('button', { name: /OBSERVED STATE CHANGES/ }).getAttribute('aria-expanded'),
    ).toBe('false');
    fireEvent.click(screen.getByRole('button', { name: /OBSERVED STATE CHANGES/ }));
    expect(again.backend.data.get(STORAGE_KEYS.workstreamCollapsed)).toBe('0');
  });

  it('keeps the tab’s toggle when storage refuses, and adopts no unnamespaced legacy key', async () => {
    const blocked = mountProject({
      hash: hash('calm/app', ':course'),
      data: CALM?.board,
      contexts: { 'calm/app\n': CALM?.context },
      storageBackend: blockedBackend() as never,
    });
    await blocked.settle();
    fireEvent.click(screen.getByRole('button', { name: /OBSERVED STATE CHANGES/ }));
    expect(
      screen.getByRole('button', { name: /OBSERVED STATE CHANGES/ }).getAttribute('aria-expanded'),
    ).toBe('false');
    blocked.unmount();
    const stray = open(CALM as never, ':course', {
      storage: { 'compass.workstream.collapsed': '1' },
    });
    await stray.settle();
    expect(
      screen.getByRole('button', { name: /OBSERVED STATE CHANGES/ }).getAttribute('aria-expanded'),
    ).toBe('true');
  });

  it('lists a change this tab observed, oldest first, and counts the unattended ones from the rows it draws', async () => {
    const calm = (state: string, generated: number) => ({
      ...(CALM?.board as { sessions: Record<string, unknown>[] }),
      generated,
      sessions: [
        { ...(CALM?.board as { sessions: Record<string, unknown>[] }).sessions[0], state },
        (CALM?.board as { sessions: unknown[] }).sessions[1],
      ],
    });
    const page = open(CALM as never, ':course');
    await page.settle();
    await page.poll(calm('idle', 1060));
    await page.poll(calm('working', 1120));
    const rows = [...document.querySelectorAll('.next-project-change')].map(
      (row) => row.textContent,
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain('became idle');
    expect(rows[1]).toContain('agent resumed');
    // Going idle ran without the reader; resuming from idle is the reader's own prompt.
    expect(screen.getByText(/1 of 2 unattended/)).toBeTruthy();
    expect(document.querySelectorAll('.next-project-change-dot--unattended')).toHaveLength(1);
  });
});

describe('disclosures keep their state by project and scope', () => {
  it('does not open at one scope what the reader opened at another', async () => {
    const page = mountProject({
      hash: hash('wait/app'),
      data: WAITING?.board,
      contexts: { 'wait/app\n': WAITING?.context },
    });
    await page.settle();
    fireEvent.click(screen.getByText('Evidence · attention sources'));
    act(() =>
      page.router.navigate({ view: 'project', project: 'wait/app', focus: 'claude:a', tab: null }),
    );
    await page.settle();
    expect(
      (
        screen
          .getByText('Evidence · attention sources')
          .closest('[data-slot=accordion]') as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(false);
    act(() =>
      page.router.navigate({ view: 'project', project: 'wait/app', focus: null, tab: null }),
    );
    await page.settle();
    expect(
      (
        screen
          .getByText('Evidence · attention sources')
          .closest('[data-slot=accordion]') as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(true);
  });

  it('keeps an opened plan open across a tab change and a poll, and does not open the same one elsewhere', async () => {
    const page = open(PLAN as never);
    await page.settle();
    const summary = screen.getByText('Show project plan');
    fireEvent.click(summary);
    fireEvent.click(screen.getByRole('tab', { name: /Course/ }));
    await page.settle();
    fireEvent.click(screen.getByRole('tab', { name: /Now/ }));
    await page.settle();
    expect(
      (
        screen.getByText('Show project plan').closest('[data-slot=accordion]') as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(true);
    await page.poll({ ...(PLAN?.board as object), generated: 1010 });
    expect(
      (
        screen.getByText('Show project plan').closest('[data-slot=accordion]') as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(true);
  });
});

describe('plain project words', () => {
  it('keeps the waiting session above the tabs and omits workflow language without a workflow', async () => {
    const board = WAITING?.board as { sessions: Record<string, unknown>[] };
    const page = open({
      ...(WAITING as NonNullable<typeof WAITING>),
      board: { ...board, sessions: board.sessions.map(({ spacedock: _workflow, ...row }) => row) },
    });
    await page.settle();
    const strip = screen.getByLabelText('Recovery summary');
    for (const label of [
      'PROJECT RECOVERY BRIEFING',
      'ASSIGNMENT',
      'EXECUTION',
      'COMMAND',
      'LATEST EVIDENCE',
      'STATED GOAL',
      'STEER · LOCAL ONLY',
      'FO is the first officer, the agent driving this workflow; Captain is you.',
      'Workflow stage conditions',
    ]) {
      expect(document.querySelector('[data-next-view-body="project"]')?.textContent).not.toContain(
        label,
      );
    }
    expect(within(strip).getByText('Where this project stands')).toBeInTheDocument();
    expect(within(strip).getByText('Current task')).toBeInTheDocument();
    expect(within(strip).getByText('Running now')).toBeInTheDocument();
    expect(within(strip).getByText('Needs you')).toBeInTheDocument();
    expect(within(strip).getByText('Latest result')).toBeInTheDocument();
    expect(within(strip).getByText('Published instruction')).toBeInTheDocument();
    const waiting = strip.querySelector('[data-next-cockpit-waiting]');
    expect(waiting?.textContent).toContain('Approve the plan?');
    expect(
      (waiting?.compareDocumentPosition(screen.getByRole('tablist')) ?? 0) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
  it('opens each project member at its Intent heading in one press', async () => {
    const page = mountProject({
      hash: '#n=projects',
      data: {
        generated: 1000,
        annotate: true,
        sessions: [
          {
            harness: 'claude',
            sid: 'a',
            project: 'p',
            state: 'working',
            first_prompt: 'Ship the queue',
            first_prompt_at: 100,
          },
        ],
      },
    });
    await page.settle();
    fireEvent.click(document.querySelector('[data-next-project-session]') as Element);
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({
      view: 'session',
      session: 'a',
      from: 'projects',
    });
    expect(document.activeElement?.id).toBe('next-session-intent-heading');
  });
});

describe('workflow vocabulary has a source', () => {
  it.each(['first-officer', 'stage-source'])('shows the authority gloss with %s', async (kind) => {
    const page = mountProject({
      hash: '#n=project:p',
      data: {
        generated: 1000,
        tripwires: { enabled: kind === 'stage-source' },
        sessions: [
          {
            harness: 'claude',
            sid: 'a',
            project: 'p',
            state: 'idle',
            ...(kind === 'first-officer' ? { spacedock: { role: 'first-officer' } } : {}),
          },
        ],
      },
    });
    await page.settle();
    expect(
      screen.getByText('FO is the first officer, the agent driving this workflow; Captain is you.'),
    ).toBeInTheDocument();
    expect(document.querySelector('[data-next-cockpit-authority-state] > span')?.textContent).toBe(
      'FO INSPECTING',
    );
  });
});

describe('project instruction and authority evidence', () => {
  const session = (sid: string, at: number | null, activity: number) => ({
    harness: 'claude',
    sid,
    project: 'p',
    state: 'working',
    last_activity: activity,
    instruction: { label: 'asked', text: `Fix COMMAND parsing ${sid}`, at },
  });
  it('chooses the newest instruction rather than the most active session', async () => {
    const page = mountProject({
      hash: '#n=project:p',
      data: {
        generated: 1000,
        sessions: [session('old', 100, 900), session('new', 800, 200)],
      },
    });
    await page.settle();
    const card = document.querySelector('.next-project-goal');
    expect(card?.querySelector('h2')?.textContent).toBe('Latest instruction');
    expect(card?.textContent).toContain('Fix COMMAND parsing new');
    expect(card?.textContent).not.toContain('Fix COMMAND parsing old');
  });
  it('does not claim an undated instruction is latest and labels saved words separately', async () => {
    const page = mountProject({
      hash: '#n=project:p:claude%3Aa',
      data: {
        generated: 1000,
        sessions: [
          {
            ...session('a', null, 900),
            annotation_goal: 'Save COMMAND exactly',
            annotation_line_1: 'Keep STATED GOAL quoted',
            annotation_revision: 1,
          },
        ],
      },
    });
    await page.settle();
    const card = document.querySelector('.next-project-goal');
    expect(card?.querySelector('h2')?.textContent).toBe('Published instruction');
    expect(card?.textContent).toContain('Your saved words');
    expect(card?.textContent).toContain('Save COMMAND exactly');
    expect(card?.textContent).toContain('Your saved words · expected outcome · line 1');
    expect(card?.textContent).toContain('Keep STATED GOAL quoted');
  });
  it.each(['pending', 'complete', 'needed'])(
    'uses plain authority states on an ordinary project: %s',
    async (state) => {
      const data = { generated: 1000, sessions: [session('a', 100, 900)] };
      const context = {
        semantic: {
          projections: {
            command_attention_coverage: { state: 'complete', scanned: 1, total: 1 },
            command_attention:
              state === 'needed'
                ? [{ owner: 'CAPTAIN', question: 'Approve COMMAND?', kind: 'ask' }]
                : [],
          },
        },
      };
      const page = mountProject({
        hash: '#n=project:p',
        data,
        contexts: state === 'pending' ? {} : { 'p\n': context },
      });
      await page.settle();
      const strip = screen.getByLabelText('Recovery summary');
      expect(strip.textContent).not.toMatch(/\bFO\b|Captain|CAPTAIN|captain/);
      expect(strip.querySelector('[data-next-cockpit-authority-state] > span')?.textContent).toBe(
        state === 'pending'
          ? 'CHECKING'
          : state === 'needed'
            ? 'NEEDS YOU'
            : 'CONTINUES · Continue the current task',
      );
    },
  );
});
