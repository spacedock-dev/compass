import { act, fireEvent, screen, within } from '@testing-library/react';
import { expect } from 'storybook/test';
import { describe, it, vi } from 'vitest';
import {
  crowdedSourceRows,
  crowdedSources,
  githubAsksPlan,
  githubPlan,
  githubPlanWithLog,
  hostileDiagramBody,
  linearPlan,
  mixedTrackerPlan,
  planBoard,
  planWaiting,
  readyPlan,
  refusedPlanSettings,
  unconfiguredPlan,
} from '../../test/plan-fixtures';
import { mountShell } from '../shell/testing';
import { FALLBACK_POLL_MS } from '../transport/live';

const shelfHref = '#n=session:Library%20pickup:codex:shelf%3Areview';
const planReadFailed = 'Compass could not read the plan. It tries again on the next refresh.';

function mountPlan(response: unknown = readyPlan, hash = '#n=plan') {
  const getResponses: Record<string, unknown> = { '/api/plan': response };
  const page = mountShell({ hash, data: planBoard, getResponses });
  return { ...page, getResponses };
}

function primary() {
  return within(screen.getByRole('navigation', { name: 'Primary' }));
}

describe('the Plan destination follows the published plan', () => {
  it.each([unconfiguredPlan, new Response('Disabled', { status: 404 })])(
    'returns an unavailable Plan bookmark to the Sessions view (%#)',
    async (response) => {
      const page = mountPlan(response);
      await page.settle();
      expect(page.gets('/api/plan')).toBe(1);
      expect(primary().queryByRole('link', { name: 'Plan' })).toBeNull();
      expect(screen.queryByRole('heading', { name: 'Plan' })).toBeNull();
      expect(screen.getByRole('heading', { name: 'All sessions', level: 2 })).toBeVisible();
      expect(document.title).toBe('Compass — Sessions');
    },
  );

  it('shows neither Sessions nor Plan on a plan bookmark until the plan read answers', async () => {
    let answer: (response: Response) => void = () => undefined;
    const page = mountPlan(() => new Promise<Response>((resolve) => (answer = resolve)));
    await page.settle();
    expect(page.gets('/api/plan')).toBe(1);
    expect(screen.queryByRole('heading', { name: 'All sessions' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Plan', level: 1 })).toBeNull();
    expect(primary().queryByRole('link', { name: 'Plan' })).toBeNull();
    await act(async () => answer(Response.json(readyPlan)));
    await page.settle();
    expect(screen.getByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
  });

  it('says a first plan read failed on the plan route instead of landing on Sessions', async () => {
    const page = mountPlan(new Response('Boom', { status: 500 }));
    await page.settle();
    expect(screen.getByText(planReadFailed, { exact: true })).toBeVisible();
    expect(primary().getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('heading', { name: 'All sessions' })).toBeNull();
    page.getResponses['/api/plan'] = readyPlan;
    await act(async () => page.clock.advance(FALLBACK_POLL_MS));
    expect(screen.getByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
    expect(screen.queryByText(planReadFailed, { exact: true })).toBeNull();
  });

  it('keeps the plan on screen through failed and unusable reads, and hides it only when the server says it is off', async () => {
    const page = mountPlan();
    await page.settle();
    const ask = 'Should the pickup shelf stay open on Sundays?';
    for (const failure of [
      new Response('Boom', { status: 500 }),
      new Response('not json', { status: 200 }),
      () => Promise.reject(new Error('offline')),
      { ...readyPlan, sources: null },
    ]) {
      page.getResponses['/api/plan'] = failure;
      await act(async () => page.clock.advance(FALLBACK_POLL_MS));
      expect(primary().getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page');
      expect(screen.getByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
      expect(screen.getByText(ask)).toBeVisible();
    }
    page.getResponses['/api/plan'] = new Response(null, { status: 404 });
    await act(async () => page.clock.advance(FALLBACK_POLL_MS));
    expect(primary().queryByRole('link', { name: 'Plan' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'All sessions', level: 2 })).toBeVisible();
  });

  it('offers Plan when the settings are refused and gives a reason without drawing the plan', async () => {
    const page = mountPlan(refusedPlanSettings);
    await page.settle();
    expect(primary().getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('The Plan settings did not have the expected format.')).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Goals' })).toBeNull();
  });

  it('joins lane and ask links to board sessions and distinguishes the published absences', async () => {
    const page = mountPlan();
    await page.settle();
    expect(primary().getByRole('link', { name: 'Plan' })).toHaveAttribute('href', '#n=plan');
    expect(screen.getByRole('heading', { name: 'Plan' })).toBeVisible();
    const links = screen.getAllByRole('link', {
      name: 'Open session Review the shelf layout, Waiting on you',
    });
    expect(links).toHaveLength(2);
    for (const link of links) expect(link).toHaveAttribute('href', `${shelfHref}&from=plan`);
    expect(screen.queryByRole('link', { name: /missing|weekend rota/i })).toBeNull();
    expect(screen.queryByText(/and \d+ more/)).toBeNull();
    expect(page.backend.requests.map(({ url }) => url.split('?')[0])).toEqual([
      '/api/data',
      '/api/plan',
    ]);
    expect(screen.getByText('Lane progress is not measured.')).toBeVisible();
    const goal = within(screen.getByRole('article', { name: 'Make library pickup easier' }));
    expect(goal.getAllByRole('listitem')).toHaveLength(3);
    expect(goal.queryByText(/\d+ of \d+ lanes/)).toBeNull();
    expect(screen.getByText('Proposed, not merged')).toBeVisible();
    const untimed = screen.getByText('Who can check the entrance signs?').closest('li');
    if (!untimed) throw new Error('The untimed ask needs a row.');
    expect(within(untimed).getByText('Library plan log', { exact: true })).toBeVisible();
    expect(within(untimed).queryByRole('time')).toBeNull();
    expect(within(untimed).queryByText(/from the log|Asked/i)).toBeNull();
    expect(screen.getByText('Marked private.')).toBeVisible();
  });

  it('lists every session waiting on you with what it asked, or a plain sentence when nothing was published', async () => {
    const page = mountPlan();
    await page.settle();
    const list = screen.getByRole('list', { name: 'Sessions waiting for a reply' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual(planWaiting.map((parts) => parts.join('')));
    for (const [title, descriptor, request] of planWaiting) {
      expect(within(list).getByRole('link', { name: title })).toHaveAccessibleDescription(
        `${descriptor} ${request}`,
      );
    }
    expect(list).not.toHaveTextContent('No exact request published');
  });

  it('counts only the lanes rendered under the goal', async () => {
    const page = mountPlan({
      ...readyPlan,
      lanes: readyPlan.lanes.map((lane) => ({
        ...lane,
        state: lane.id === 'shelf' ? 'done' : 'not_started',
      })),
    });
    await page.settle();
    const goal = within(screen.getByRole('article', { name: 'Make library pickup easier' }));
    expect(goal.getByText('1 of 3 lanes are done', { exact: true })).toBeVisible();
    expect(goal.getAllByRole('listitem')).toHaveLength(3);
    expect(goal.queryByText('1 of 5 lanes are done')).toBeNull();
  });

  it('groups lanes by their published state and counts only the measured, kept ones', async () => {
    const published = [
      ['blocked', 'Blocked'],
      ['waiting', 'Waiting'],
      ['running', 'In progress'],
      ['not_started', 'Planned'],
      ['done', 'Done'],
      ['dropped', 'Dropped'],
      ['Status not recognised', 'Status not recognised'],
      [null, 'Not measured'],
      ['parked', 'Not measured'],
    ] as const;
    const lanes = published.map(([state], index) => ({
      ...readyPlan.lanes[2],
      id: `lane-${String(index)}`,
      title: `Lane ${String(index)}`,
      state,
    }));
    const page = mountPlan({
      ...readyPlan,
      goals: [{ ...readyPlan.goals[0], lanes: lanes.map(({ id }) => id) }],
      lanes,
    });
    await page.settle();
    const goal = within(screen.getByRole('article', { name: 'Make library pickup easier' }));
    expect(goal.getAllByRole('heading', { level: 4 }).map((el) => el.textContent)).toEqual([
      ...new Set(published.map(([, word]) => word)),
    ]);
    for (const [index, [, word]] of published.entries()) {
      expect(
        within(goal.getByRole('list', { name: word })).getByText(`Lane ${String(index)}`),
      ).toBeVisible();
    }
    expect(goal.getByText('1 of 5 lanes are done', { exact: true })).toBeVisible();
    expect(
      goal.getByText('Dropped lanes and lanes without a known status are not counted.', {
        exact: true,
      }),
    ).toBeVisible();
    expect(goal.queryByText('parked')).toBeNull();
  });

  it('draws an ask the settings keep wordless as a plain sentence, and drops only a broken ask', async () => {
    const page = mountPlan({
      ...readyPlan,
      asks: [{ id: 'broken' }, { ...readyPlan.asks[0], text: null }, readyPlan.asks[1]],
    });
    await page.settle();
    const asks = within(screen.getByRole('list', { name: 'Open asks' }));
    const rows = asks.getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    const wordless = within(rows[0] as HTMLElement).getByText('An open ask with no text', {
      exact: true,
    });
    expect(wordless).toBeVisible();
    expect(wordless.closest('[data-authored]')).toBeNull();
    expect(asks.getByText('Who can check the entrance signs?')).toBeVisible();
  });

  it('opens a session from Plan and returns to Plan by the crumb and by Escape', async () => {
    const page = mountPlan();
    await page.settle();
    const [link] = screen.getAllByRole('link', {
      name: 'Open session Review the shelf layout, Waiting on you',
    });
    if (!link) throw new Error('The lane needs its session link.');
    expect(link).toHaveAttribute('href', `${shelfHref}&from=plan`);
    await act(async () => fireEvent.click(link));
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({ view: 'session', from: 'plan' });
    const crumb = within(screen.getByRole('navigation', { name: 'Breadcrumb' }));
    expect(crumb.getByRole('link', { name: 'Plan' })).toHaveAttribute('href', '#n=plan');
    expect(primary().getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page');
    await act(async () => fireEvent.keyDown(document.body, { key: 'Escape' }));
    await page.settle();
    expect(screen.getByRole('heading', { name: 'Plan', level: 1 })).toBeVisible();
  });

  it('sends a session opened from Plan back to Sessions when there is no plan', async () => {
    const page = mountPlan(unconfiguredPlan, `${shelfHref}&from=plan`);
    await page.settle();
    const crumb = within(screen.getByRole('navigation', { name: 'Breadcrumb' }));
    expect(crumb.getByRole('link', { name: 'Sessions' })).toHaveAttribute('href', '#n=sessions');
    expect(crumb.queryByRole('link', { name: 'Plan' })).toBeNull();
    expect(primary().getByRole('link', { name: 'Sessions' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    await act(async () => fireEvent.keyDown(document.body, { key: 'Escape' }));
    await page.settle();
    expect(screen.getByRole('heading', { name: 'All sessions', level: 2 })).toBeVisible();
    expect(page.router.getRoute().view).toBe('sessions');
  });

  it('keeps a design note that is not decided out of Product decisions', async () => {
    const page = mountPlan({
      ...readyPlan,
      design: [
        ...readyPlan.design,
        { ...readyPlan.design[0], title: 'Add pickup lockers', decided: false },
      ],
    });
    await page.settle();
    const decided = within(screen.getByRole('list', { name: 'Product decisions' }));
    expect(decided.getAllByRole('listitem')).toHaveLength(1);
    expect(decided.queryByText('Add pickup lockers')).toBeNull();
    const open = within(screen.getByRole('list', { name: 'Not decided yet' }));
    expect(open.getByText('Add pickup lockers')).toBeVisible();
  });

  it.each([
    ['missing', 'The file is missing.'],
    ['unreadable', 'The source could not be read.'],
    ['not an owned regular file', 'The file is not a regular file you own.'],
    ['symbolic link', 'The file is a symbolic link.'],
    ['hard link', 'The same file has another name.'],
    ['private', 'Marked private.'],
    ['over the byte cap', 'The file is larger than Compass reads.'],
    ['over the row cap', 'The file has more rows than Compass reads.'],
    [
      'over the brief folder entry cap',
      'The lane-brief folder has more entries than Compass reads.',
    ],
    [
      'guarded plan reads are unavailable on this platform',
      'Compass cannot read plan files on this platform.',
    ],
    ['file changed before it could be read', 'The file changed while Compass read it.'],
    ['malformed', 'The source did not have the expected format.'],
    ['Status not recognised', 'Compass did not recognise a status the source needs.'],
    ['not named in settings', 'The Plan settings do not name this file.'],
    ['outside declared root', 'The file is outside the folder the Plan settings declare.'],
    ['git reads are off', 'Git reads are off.'],
    ['git timed out', 'Git did not answer in time.'],
    ['git unavailable', 'Git is not available.'],
    ['branch missing', 'The branch is missing.'],
    ['not in branch', 'The file is not on the branch.'],
    ['not a regular file in branch', 'The file on the branch is not a regular file.'],
    ['unsafe lane identifier', 'The lane name has characters Compass does not accept.'],
    ['a reason from a newer server', 'The source could not be read.'],
  ])('says why a source was refused: %s', async (reason, sentence) => {
    const page = mountPlan({
      ...readyPlan,
      sources: [
        {
          label: 'Pickup tracker',
          kind: 'tracker',
          fileLabel: null,
          position: null,
          state: 'refused',
          reason,
        },
      ],
    });
    await page.settle();
    const row = within(screen.getByRole('region', { name: 'Sources' })).getByRole('listitem');
    expect(within(row).getByText('Refused', { exact: true })).toBeVisible();
    expect(within(row).getByText(sentence, { exact: true })).toBeVisible();
    // The server's own words never reach the page; only the sentence does.
    expect(row.textContent).toBe(`Pickup trackerRefused${sentence}`);
  });

  it('tells files of one kind apart, folds a missing draft branch and counts the lane briefs', async () => {
    const page = mountPlan({ ...readyPlan, sources: crowdedSources });
    await page.settle();
    const rows = within(screen.getByRole('region', { name: 'Sources' })).getAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual(crowdedSourceRows);
  });

  it('names a draft file that was read by its label or its kind and place', async () => {
    const file = (kind: string, position: number | null, fileLabel: string | null) => ({
      label: 'Model ship',
      kind,
      fileLabel,
      position,
      state: 'ok',
      reason: null,
    });
    const page = mountPlan({
      ...readyPlan,
      sources: [
        file('inventory', 1, null),
        file('inventory', 2, 'Spare parts'),
        file('draft inventory', 1, null),
        file('draft inventory', 2, 'Spare parts'),
        // A newer server's place that is not a whole number drops only that row.
        file('tracker', 1.5, null),
        {
          label: 'Lane briefs',
          kind: 'lane briefs',
          fileLabel: null,
          position: null,
          state: 'ok',
          reason: null,
        },
      ],
    });
    await page.settle();
    const rows = within(screen.getByRole('region', { name: 'Sources' })).getAllByRole('listitem');
    expect(rows.map((row) => row.textContent)).toEqual([
      'Model ship · inventory 1Read',
      'Model ship · Spare partsRead',
      'Model ship · draft · inventory 1Read',
      'Model ship · draft · Spare partsRead',
      'Lane briefsRead',
    ]);
  });

  it.each([
    [
      'a draft file refused for another reason keeps its own row',
      [
        ['Model ship', 'inventory', 1, null],
        ['Model ship', 'inventory', 2, null],
        ['Model ship', 'draft inventory', 1, 'private'],
        ['Model ship', 'draft inventory', 2, 'branch missing'],
      ],
      [
        'Model ship · inventory 1Read',
        'Model ship · inventory 2Read',
        'Model ship · draft · inventory 1RefusedMarked private.',
        'Model ship · draftRefusedThe branch is missing.',
      ],
    ],
    [
      'a missing primary branch keeps one row per file',
      [
        ['Model ship', 'inventory', 1, 'branch missing'],
        ['Model ship', 'inventory', 2, 'branch missing'],
      ],
      [
        'Model ship · inventory 1RefusedThe branch is missing.',
        'Model ship · inventory 2RefusedThe branch is missing.',
      ],
    ],
    [
      'two repositories with a missing draft branch get a folded row each',
      [
        ['Model ship', 'goals', null, null],
        ['Model ship', 'draft goals', null, 'branch missing'],
        ['Lamp', 'goals', null, null],
        ['Lamp', 'draft goals', null, 'branch missing'],
        ['Lamp', 'draft tracker', null, 'branch missing'],
      ],
      [
        'Model ship · goalsRead',
        'Model ship · draftRefusedThe branch is missing.',
        'Lamp · goalsRead',
        'Lamp · draftRefusedThe branch is missing.',
      ],
    ],
    [
      'a refused brief shows when no brief was read',
      [
        ['Lane briefs', 'lane briefs', null, null],
        ['mast', 'lane brief', null, 'malformed'],
      ],
      ['Lane briefs0 read', 'Lane brief · mastRefusedThe source did not have the expected format.'],
    ],
    [
      'refused briefs without a lane name are counted by reason',
      [
        ['Lane briefs', 'lane briefs', null, null],
        ['deck', 'lane brief', null, null],
        ['', 'lane brief', null, 'unsafe lane identifier'],
        ['', 'lane brief', null, 'malformed'],
        ['', 'lane brief', null, 'malformed'],
      ],
      [
        'Lane briefs1 read',
        'Lane briefRefusedThe lane name has characters Compass does not accept.',
        '2 lane briefsRefusedThe source did not have the expected format.',
      ],
    ],
  ] as const)(
    'groups sources only where they say one thing: %s',
    async (_case, published, rows) => {
      const page = mountPlan({
        ...readyPlan,
        sources: published.map(([label, kind, position, reason]) => ({
          label,
          kind,
          fileLabel: null,
          position,
          state: reason === null ? 'ok' : 'refused',
          reason,
        })),
      });
      await page.settle();
      const items = within(screen.getByRole('region', { name: 'Sources' })).getAllByRole(
        'listitem',
      );
      expect(items.map((row) => row.textContent)).toEqual(rows);
    },
  );

  it('draws two goals that share an id, each once, without a duplicate key', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      const page = mountPlan({
        ...readyPlan,
        goals: [readyPlan.goals[0], { ...readyPlan.goals[1], id: readyPlan.goals[0].id }],
      });
      await page.settle();
      expect(screen.getAllByRole('article')).toHaveLength(2);
      expect(error.mock.calls.flat().join(' ')).not.toMatch(/same key/);
    } finally {
      error.mockRestore();
    }
  });

  it('names the refused and failed Plan pages as regions', async () => {
    const page = mountPlan(refusedPlanSettings);
    await page.settle();
    expect(screen.getByRole('region', { name: 'Plan' })).toHaveAttribute(
      'data-next-view-body',
      'plan',
    );
  });

  it('draws only the diagram caption and hosts from a hostile diagram', async () => {
    const page = mountPlan({
      ...readyPlan,
      diagrams: [{ ...readyPlan.diagrams[0], body: hostileDiagramBody }],
    });
    await page.settle();
    const diagrams = screen.getByRole('region', { name: 'Diagrams' });
    expect(within(diagrams).getByText('diagrams.example.org')).toBeVisible();
    expect(diagrams.querySelector('img, script, a')).toBeNull();
    expect(diagrams).not.toHaveTextContent(/plan-image|Run diagram|javascript:/);
  });

  it('refreshes the plan and the joined session names on the board safety poll without remounting its links', async () => {
    const page = mountPlan();
    await page.settle();
    const name = 'Open session Review the shelf layout, Waiting on you';
    const link = screen.getAllByRole('link', { name })[0];
    link?.focus();
    page.backend.data = {
      ...planBoard,
      sessions: [{ ...planBoard.sessions[0], title: 'Review the new shelf layout' }],
    };
    page.getResponses['/api/plan'] = {
      ...readyPlan,
      asks: [{ ...readyPlan.asks[0], text: 'Who can review the new shelf layout?' }],
    };
    await act(async () => page.clock.advance(FALLBACK_POLL_MS));
    expect(page.gets('/api/plan')).toBe(2);
    expect(link).toHaveAccessibleName('Open session Review the new shelf layout, Waiting on you');
    expect(link).toHaveFocus();
    expect(screen.getByText('Who can review the new shelf layout?')).toBeVisible();
    expect(screen.queryByText(readyPlan.asks[0].text)).toBeNull();

    page.getResponses['/api/plan'] = unconfiguredPlan;
    await act(async () => page.clock.advance(FALLBACK_POLL_MS));
    expect(primary().queryByRole('link', { name: 'Plan' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Plan' })).toBeNull();
  });
});

describe('tracker plans on Plan', () => {
  it('shows Linear source states and keeps target and completion dates distinct', async () => {
    const page = mountPlan(linearPlan);
    await page.settle();
    const sources = within(screen.getByRole('region', { name: 'Sources' }));
    expect(sources.getAllByRole('listitem').map((row) => row.textContent)).toEqual([
      'Linear projectRead',
      'Linear project milestoneRead',
    ]);
    const project = within(screen.getByRole('article', { name: 'Survey the orchard' }));
    expect(project.getByText(/^Target /)).toHaveAttribute('datetime', '2026-11-06');
    expect(
      project.getAllByText(/^Completed /).map((date) => date.getAttribute('datetime')),
    ).toEqual(['2026-11-05T16:00:00Z', '2026-11-03T16:00:00Z']);
    const milestone = within(screen.getByRole('article', { name: 'Finish the north plot' }));
    expect(milestone.getByText(/^Target /)).toHaveAttribute('datetime', '2026-11-04');
    expect(milestone.getByText(/^Completed /)).toHaveAttribute('datetime', '2026-11-03T16:00:00Z');
    expect(milestone.getByRole('link', { name: /Review the shelf layout/ })).toBeVisible();
    expect(screen.queryByText('Tracker asks are not measured.')).toBeNull();
    expect(screen.queryByText('No tracker asks.')).toBeNull();
  });

  it.each(['mixed', 'reverse mixed'] as const)(
    'withdraws only the expired tracker while a refresh is pending (%s)',
    async (scenario) => {
      const github = githubAsksPlan('present');
      const linearFirst = scenario === 'mixed';
      const [first, second] = linearFirst ? [linearPlan, github] : [github, linearPlan];
      const firstTitle = first.goals[0].title;
      const secondTitle = second.goals[0].title;
      const nextSources = [
        ...first.sources.map((source) => ({ ...source, state: 'expired', reason: 'expired' })),
        ...second.sources,
      ];
      const page = mountPlan({
        ...mixedTrackerPlan,
        goals: [...first.goals, ...second.goals],
        lanes: [...first.lanes, ...second.lanes],
        sources: [...first.sources, ...second.sources],
        trackerAsksFreshForMs: linearFirst ? 30_000 : 1_000,
        trackerRead: {
          freshForMs: 1_000,
          localGoals: [],
          localLanes: [],
          updates: [
            {
              freshForMs: 30_000,
              sources: nextSources,
              goals: { remove: first.goals.map(({ id }) => id), upsert: [] },
              lanes: { remove: first.lanes.map(({ id }) => id), upsert: [] },
            },
          ],
        },
      });
      await page.settle();
      expect(screen.getByRole('article', { name: firstTitle })).toBeVisible();
      const survivingCard = screen.getByRole('article', { name: secondTitle });
      expect(survivingCard).toBeVisible();
      page.getResponses['/api/plan'] = () => new Promise<Response>(() => undefined);
      await act(async () => page.clock.advance(1_000));
      const sources = within(screen.getByRole('region', { name: 'Sources' }));
      const waiting = within(screen.getByRole('region', { name: 'Waiting on you' }));
      expect(sources.getAllByText('The last read is out of date.')).toHaveLength(
        first.sources.length,
      );
      expect(sources.getAllByText('Read')).toHaveLength(second.sources.length);
      expect(screen.queryByRole('article', { name: firstTitle })).toBeNull();
      expect(screen.getByRole('article', { name: secondTitle })).toBe(survivingCard);
      const ask = waiting.queryByRole('link', { name: 'Approve the sign lettering' });
      if (linearFirst) expect(ask).toBeVisible();
      else expect(ask).toBeNull();
      await act(async () => page.clock.advance(29_000));
      expect(screen.queryByRole('article', { name: secondTitle })).toBeNull();
      expect(waiting.queryByRole('link', { name: 'Approve the sign lettering' })).toBeNull();
      expect(waiting.getByText('Tracker asks are not measured.')).toBeVisible();
    },
  );

  it('restores a shared GitHub lane from the remaining source when its sibling expires', async () => {
    const github = githubAsksPlan('present');
    const [firstGoal] = github.goals;
    const [firstSource] = github.sources;
    const [lane] = githubPlan('ok').lanes;
    if (!firstGoal || !firstSource || !lane)
      throw new Error('Expected a complete tracker fixture.');
    const secondGoal = { ...firstGoal, id: 'github-project', title: 'Prepare the library opening' };
    const secondSource = { ...firstSource, label: 'GitHub project', kind: 'github project' };
    const page = mountPlan({
      ...github,
      goals: [firstGoal, secondGoal],
      lanes: [{ ...lane, state: null }],
      sources: [firstSource, secondSource],
      trackerAsksFreshForMs: 1_000,
      trackerRead: {
        freshForMs: 1_000,
        localGoals: [],
        localLanes: [],
        updates: [
          {
            freshForMs: 11_000,
            goals: { remove: [firstGoal.id], upsert: [] },
            lanes: { remove: [], upsert: [lane] },
            sources: [{ ...firstSource, state: 'expired', reason: 'expired' }, secondSource],
          },
        ],
      },
    });
    await page.settle();
    const fresh = within(screen.getByRole('article', { name: secondGoal.title }));
    expect(fresh.getByText('Lane progress is not measured.')).toBeVisible();
    page.getResponses['/api/plan'] = () => new Promise<Response>(() => undefined);
    await act(async () => page.clock.advance(1_000));
    expect(screen.queryByRole('article', { name: firstGoal.title })).toBeNull();
    const survivingGoal = within(screen.getByRole('article', { name: secondGoal.title }));
    expect(survivingGoal.getByText('1 of 1 lane is done')).toBeVisible();
    expect(survivingGoal.getByText(lane.title)).toBeVisible();
    expect(screen.getByText('Tracker asks are not measured.')).toBeVisible();
  });

  it.each([
    ['unknown-workspace', 'Sign in to the declared workspace with your tracker CLI.'],
    ['missing-team-scope', 'Set a default team in your tracker CLI.'],
  ] as const)('explains the tracker refusal %s in Sources', async (reason, explanation) => {
    const page = mountPlan({
      ...linearPlan,
      goals: [],
      lanes: [],
      trackerRead: null,
      sources: [{ ...linearPlan.sources[0], state: 'refused', reason }],
    });
    await page.settle();
    const row = within(
      within(screen.getByRole('region', { name: 'Sources' })).getByRole('listitem'),
    );
    expect(row.getByText(explanation)).toBeVisible();
  });

  it.each([
    ['empty', null, 'No lanes found'],
    ['refreshing', 'refreshing', 'Reading Linear…'],
    ['refused', 'signed-out', 'Sign in to Linear with your Linear CLI.'],
    ['refused', 'partial-result', 'Linear returned an incomplete read.'],
  ] as const)('shows the Linear source state %s (%s)', async (state, reason, message) => {
    const page = mountPlan({
      ...linearPlan,
      goals: state === 'empty' ? [{ ...linearPlan.goals[0], lanes: [] }] : [],
      lanes: [],
      trackerRead: state === 'empty' ? linearPlan.trackerRead : null,
      sources: [{ ...linearPlan.sources[0], state, reason }],
    });
    await page.settle();
    const source = within(screen.getByRole('region', { name: 'Sources' }));
    expect(source.getByText(message)).toBeVisible();
    expect(screen.queryAllByRole('article')).toHaveLength(state === 'empty' ? 1 : 0);
    expect(screen.queryByText('Map the old apple trees')).toBeNull();
    if (state !== 'empty') {
      expect(screen.getByText('Lane progress is not measured.')).toBeVisible();
    }
  });

  it.each([
    [null, null],
    ['decisions', 'Design'],
    ['tracker', 'Tracker'],
    ['diagrams', 'Diagrams'],
  ] as const)('shows only file sections declared in a sparse plan (%s)', async (kind, section) => {
    const page = mountPlan({
      ...githubPlanWithLog,
      sources: kind
        ? [
            ...githubPlanWithLog.sources,
            {
              label: 'Declared file',
              kind,
              fileLabel: null,
              position: null,
              state: 'refused',
              reason: 'not in branch',
            },
          ]
        : githubPlanWithLog.sources,
    });
    await page.settle();
    expect(screen.getByText(readyPlan.asks[0].text)).toBeVisible();
    expect(screen.getByText('Put up the welcome sign')).toBeVisible();
    for (const name of ['Design', 'Tracker', 'Diagrams']) {
      const heading = screen.queryByRole('heading', { name, level: 2 });
      if (name === section) expect(heading).toBeVisible();
      else expect(heading).toBeNull();
    }
  });

  it('shows a refused lane folder without adding file sections to a tracker-only plan', async () => {
    const tracker = githubPlan('ok');
    const page = mountPlan({
      ...tracker,
      sources: [
        ...tracker.sources,
        {
          kind: 'lane folder',
          label: 'github-issue',
          state: 'refused',
          reason: 'missing',
          fileLabel: null,
          position: null,
        },
      ],
    });
    await page.settle();
    const sources = within(screen.getByRole('region', { name: 'Sources' }));
    expect(sources.getByText('github-issue')).toBeVisible();
    expect(sources.getByText('Refused')).toBeVisible();
    for (const name of ['Design', 'Tracker', 'Diagrams']) {
      expect(screen.queryByRole('heading', { name, level: 2 })).toBeNull();
    }
  });

  it('collects a tracker read before the safety poll and requests another at expiry', async () => {
    const page = mountPlan(githubPlan('refreshing'));
    await page.settle();
    const remote = githubPlan('ok');
    page.getResponses['/api/plan'] = {
      ...remote,
      trackerRead: { ...remote.trackerRead, freshForMs: 30_000 },
    };
    await act(async () => page.clock.advance(1_000));
    expect(page.gets('/api/plan')).toBe(2);
    expect(screen.getByText('Put up the welcome sign')).toBeVisible();
    page.getResponses['/api/plan'] = {
      ...remote,
      trackerRead: { ...remote.trackerRead, freshForMs: 11_000 },
    };
    await act(async () => page.clock.advance(FALLBACK_POLL_MS - 1_000));
    expect(page.gets('/api/plan')).toBe(3);
    page.getResponses['/api/plan'] = githubPlan('refreshing');
    await act(async () => page.clock.advance(11_000));
    expect(page.gets('/api/plan')).toBe(4);
    expect(screen.queryByText('Put up the welcome sign')).toBeNull();
  });

  it('retries when a response runs out of freshness before reaching the page', async () => {
    let respond: (response: Response) => void = () => undefined;
    const page = mountPlan(() => new Promise<Response>((resolve) => (respond = resolve)));
    await page.settle();
    const remote = githubPlan('ok');
    await act(async () => page.clock.advance(100));
    await act(async () =>
      respond(Response.json({ ...remote, trackerRead: { ...remote.trackerRead, freshForMs: 50 } })),
    );
    expect(screen.queryByText('Put up the welcome sign')).toBeNull();
    expect(screen.getByText('The last read is out of date.')).toBeVisible();
    page.getResponses['/api/plan'] = remote;
    await act(async () => page.clock.advance(1_000));
    expect(screen.getByText('Put up the welcome sign')).toBeVisible();
  });

  it('clears active reading when a tracker retry fails and keeps file rows visible', async () => {
    const remote = githubPlan('refreshing');
    const page = mountPlan({ ...readyPlan, sources: [...readyPlan.sources, ...remote.sources] });
    await page.settle();
    const sources = within(screen.getByRole('region', { name: 'Sources' }));
    expect(sources.getByText('Reading GitHub…')).toBeVisible();
    page.getResponses['/api/plan'] = () => Promise.reject(new Error('offline'));
    await act(async () => page.clock.advance(1_000));
    expect(sources.queryByText('Reading GitHub…')).toBeNull();
    expect(sources.getByText('Compass could not refresh the plan.')).toBeVisible();
    expect(screen.getByText(readyPlan.asks[0].text)).toBeVisible();
  });

  it('shows the issue title as a host-only link in Waiting on you', async () => {
    const page = mountPlan(githubAsksPlan('present'));
    await page.settle();
    const waiting = within(screen.getByRole('region', { name: 'Waiting on you' }));
    const asks = within(waiting.getByRole('list', { name: 'Tracker asks' }));
    const link = asks.getByRole('link', { name: 'Approve the sign lettering' });
    expect(link).toBeVisible();
    expect(link).toHaveAttribute('href', 'https://github.com');
    expect(asks.getByText('GitHub milestone · github.com')).toBeVisible();
    expect(waiting.queryByText('Tracker asks are not measured.')).toBeNull();
  });

  it('shows a measured absence when no issues match', async () => {
    const page = mountPlan(githubAsksPlan('none'));
    await page.settle();
    expect(screen.getByText('No tracker asks.')).toBeVisible();
    expect(screen.queryByText('Tracker asks are not measured.')).toBeNull();
  });

  it('keeps the other waits visible when tracker asks are not measured', async () => {
    const page = mountPlan(githubAsksPlan('not measured'));
    await page.settle();
    const waiting = within(screen.getByRole('region', { name: 'Waiting on you' }));
    expect(waiting.getByText('Tracker asks are not measured.')).toBeVisible();
    expect(waiting.queryByText('No tracker asks.')).toBeNull();
    expect(waiting.getByText('Who can check the entrance signs?')).toBeVisible();
    expect(waiting.getByRole('link', { name: 'Review the shelf layout' })).toBeVisible();
  });

  it('does not claim a measurement for a malformed ask row', async () => {
    const plan = githubAsksPlan('present');
    const page = mountPlan({
      ...plan,
      trackerAsks: [{ ...plan.trackerAsks?.[0], linkHost: 'github.com/private-repo' }],
    });
    await page.settle();
    expect(screen.getByText('Tracker asks are not measured.')).toBeVisible();
    expect(screen.getByText('Who can check the entrance signs?')).toBeVisible();
    expect(screen.queryByRole('link', { name: 'Approve the sign lettering' })).toBeNull();
  });

  it.each(['present', 'none'] as const)(
    'keeps tracker asks (%s) through an earlier source expiry while a refresh is pending',
    async (state) => {
      const plan = githubAsksPlan(state);
      const page = mountPlan({
        ...plan,
        sources: [
          ...plan.sources,
          { ...plan.sources[0], kind: 'github parent-issue', label: 'GitHub parent issue' },
        ],
        trackerRead: { ...plan.trackerRead, freshForMs: 20_000 },
        trackerAsksFreshForMs: 30_000,
      });
      await page.settle();
      const waiting = within(screen.getByRole('region', { name: 'Waiting on you' }));
      const measurement = () =>
        state === 'present'
          ? waiting.queryByRole('list', { name: 'Tracker asks' })
          : waiting.queryByText('No tracker asks.');
      expect(measurement()).toBeVisible();
      page.getResponses['/api/plan'] = () => new Promise<Response>(() => undefined);
      await act(async () => page.clock.advance(20_000));
      expect(page.gets('/api/plan')).toBeGreaterThan(1);
      expect(measurement()).toBeVisible();
      expect(waiting.queryByText('Tracker asks are not measured.')).toBeNull();
      await act(async () => page.clock.advance(10_000));
      expect(measurement()).toBeNull();
      expect(waiting.getByText('Tracker asks are not measured.')).toBeVisible();
      expect(waiting.getByText(readyPlan.asks[0].text)).toBeVisible();
      expect(waiting.getByRole('link', { name: 'Review the shelf layout' })).toBeVisible();
    },
  );

  it('shows a due date, a complete lane count and its linked session', async () => {
    const page = mountPlan(githubPlan('ok'));
    await page.settle();
    const goal = within(screen.getByRole('article', { name: 'Open the new library' }));
    expect(goal.getByText(/Due /)).toHaveAttribute('datetime', '2026-12-08');
    expect(goal.getByText('1 of 1 lane is done')).toBeVisible();
    expect(goal.getByRole('link', { name: /Review the shelf layout/ })).toBeVisible();
  });

  it('distinguishes a complete empty read from missing measurements', async () => {
    const page = mountPlan(githubPlan('empty'));
    await page.settle();
    expect(screen.getByText('No lanes serve this goal yet')).toBeVisible();
    expect(screen.getByText('No lanes found')).toBeVisible();
  });

  it.each([false, true])(
    'keeps the tracker-ask limit through goal reads (local asks: %s)',
    async (withLocalAsks) => {
      const reply = (state: 'refreshing' | 'ok' | 'empty') => ({
        ...githubPlan(state),
        trackerAsksEnabled: true,
        asks: withLocalAsks ? readyPlan.asks : [],
      });
      const getResponses = { '/api/plan': reply('refreshing') };
      const page = mountShell({ hash: '#n=plan', data: { sessions: [] }, getResponses });
      await page.settle();
      const waiting = within(screen.getByRole('region', { name: 'Waiting on you' }));
      const expectDisclosure = () => {
        expect(waiting.getByText('Tracker asks are not measured.')).toBeVisible();
        if (withLocalAsks) expect(waiting.getByText(readyPlan.asks[0].text)).toBeVisible();
      };
      expectDisclosure();
      getResponses['/api/plan'] = reply('ok');
      await act(async () => page.clock.advance(1_000));
      expect(screen.getByText('Put up the welcome sign')).toBeVisible();
      expectDisclosure();
      getResponses['/api/plan'] = reply('empty');
      await act(async () => page.clock.advance(FALLBACK_POLL_MS - 1_000));
      expect(screen.getByText('No lanes serve this goal yet')).toBeVisible();
      expectDisclosure();
    },
  );

  it.each([
    ['refused', 'Sign in to GitHub with your GitHub CLI.'],
    ['refreshing', 'Reading GitHub…'],
    ['expired', 'The last read is out of date.'],
  ] as const)('says progress is not measured when the source is %s', async (state, reason) => {
    const page = mountPlan(githubPlan(state));
    await page.settle();
    expect(screen.getByText(reason)).toBeVisible();
    expect(screen.getByText('Lane progress is not measured.')).toBeVisible();
    expect(screen.queryByText('No goals are listed.')).toBeNull();
  });

  it.each([
    ['refused', 'signed-out', 'Sign in to Linear with your Linear CLI.'],
    ['refused', 'partial-result', 'Linear returned an incomplete read.'],
    ['refreshing', 'refreshing', 'Reading Linear…'],
    ['expired', 'expired', 'The last read is out of date.'],
  ] as const)(
    'keeps the GitHub count when Linear is %s (%s)',
    async (state, reason, explanation) => {
      const github = githubAsksPlan('present');
      const page = mountPlan({
        ...github,
        sources: [...github.sources, { ...linearPlan.sources[0], state, reason }],
      });
      await page.settle();
      const goal = within(screen.getByRole('article', { name: 'Open the new library' }));
      expect(goal.getByText('0 of 1 lane is done')).toBeVisible();
      const sources = within(screen.getByRole('region', { name: 'Sources' }));
      expect(sources.getByText(explanation)).toBeVisible();
      expect(sources.getByText('Not measured.')).toBeVisible();
    },
  );

  it.each(['Linear', 'GitHub'] as const)(
    'keeps the complete %s goal counts alongside a partial GitHub source',
    async (provider) => {
      const measured = provider === 'Linear' ? linearPlan : githubPlan('ok');
      const page = mountPlan({
        ...measured,
        sources: [
          ...measured.sources,
          {
            ...githubPlan('refused').sources[0],
            kind: 'github project',
            label: 'GitHub project',
            reason: 'partial-result',
          },
        ],
      });
      await page.settle();
      const sources = within(screen.getByRole('region', { name: 'Sources' }));
      expect(sources.getByText('GitHub returned an incomplete read.')).toBeVisible();
      for (const { title } of measured.goals) {
        const goal = within(screen.getByRole('article', { name: title }));
        expect(goal.getByText('1 of 1 lane is done')).toBeVisible();
      }
    },
  );

  it('withdraws tracker rows and counts after a failed refresh while keeping local rows', async () => {
    const remote = githubPlan('ok');
    const page = mountPlan({
      ...remote,
      goals: [...readyPlan.goals, ...remote.goals],
      lanes: [...readyPlan.lanes, ...remote.lanes],
      trackerRead: {
        ...remote.trackerRead,
        localGoals: readyPlan.goals,
        localLanes: readyPlan.lanes,
      },
    });
    await page.settle();
    expect(screen.getByText('Put up the welcome sign')).toBeVisible();
    page.getResponses['/api/plan'] = new Response(null, { status: 503 });
    await act(async () => page.clock.advance(FALLBACK_POLL_MS));
    expect(screen.queryByText('Put up the welcome sign')).toBeNull();
    expect(screen.getByText('Set up the pickup shelf')).toBeVisible();
    expect(screen.queryAllByText(/ of .* lanes? (?:is|are) done/)).toHaveLength(0);
  });

  it('withdraws a tracker read when its freshness time runs out', async () => {
    const remote = githubPlan('ok');
    const page = mountPlan({ ...remote, trackerRead: { ...remote.trackerRead, freshForMs: 100 } });
    await page.settle();
    expect(screen.getByText('Put up the welcome sign')).toBeVisible();
    page.getResponses['/api/plan'] = new Response(null, { status: 503 });
    await act(async () => page.clock.advance(100));
    expect(screen.queryByText('Put up the welcome sign')).toBeNull();
    expect(screen.getByText('The last read is out of date.')).toBeVisible();
  });

  it('withdraws a still-fresh ask when the pending refresh fails', async () => {
    const plan = githubAsksPlan('present');
    const page = mountPlan({ ...plan, trackerRead: { ...plan.trackerRead, freshForMs: 100 } });
    await page.settle();
    let respond: (response: Response) => void = () => undefined;
    page.getResponses['/api/plan'] = () => new Promise<Response>((resolve) => (respond = resolve));
    await act(async () => page.clock.advance(100));
    const waiting = within(screen.getByRole('region', { name: 'Waiting on you' }));
    expect(waiting.getByRole('link', { name: 'Approve the sign lettering' })).toBeVisible();
    await act(async () => respond(new Response(null, { status: 503 })));
    expect(waiting.queryByRole('list', { name: 'Tracker asks' })).toBeNull();
    expect(waiting.getByText('Tracker asks are not measured.')).toBeVisible();
    expect(waiting.getByText(readyPlan.asks[0].text)).toBeVisible();
  });
});
