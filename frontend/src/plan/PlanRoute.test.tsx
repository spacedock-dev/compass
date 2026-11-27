import { act, screen, within } from '@testing-library/react';
import { expect } from 'storybook/test';
import { describe, it } from 'vitest';
import {
  hostileDiagramBody,
  planBoard,
  readyPlan,
  refusedPlanSettings,
  unconfiguredPlan,
} from '../../test/plan-fixtures';
import { mountShell } from '../shell/testing';
import { FALLBACK_POLL_MS } from '../transport/live';

function mountPlan(response: unknown = readyPlan) {
  const getResponses = { '/api/plan': response };
  const page = mountShell({ hash: '#n=plan', data: planBoard, getResponses });
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
    for (const link of links)
      expect(link).toHaveAttribute('href', '#n=session:Library%20pickup:codex:shelf%3Areview');
    expect(screen.queryByRole('link', { name: /missing|weekend rota/i })).toBeNull();
    expect(screen.queryByText(/and \d+ more/)).toBeNull();
    expect(page.backend.requests.map(({ url }) => url.split('?')[0])).toEqual([
      '/api/data',
      '/api/plan',
    ]);
    expect(screen.getByText('Lane progress is not published.')).toBeVisible();
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

  it('counts only the lanes rendered under the goal', async () => {
    const page = mountPlan({
      ...readyPlan,
      lanes: readyPlan.lanes.map((lane) => ({
        ...lane,
        state: lane.id === 'shelf' ? 'done' : 'planned',
      })),
    });
    await page.settle();
    const goal = within(screen.getByRole('article', { name: 'Make library pickup easier' }));
    expect(goal.getByText('1 of 3 lanes are done', { exact: true })).toBeVisible();
    expect(goal.getAllByRole('listitem')).toHaveLength(3);
    expect(goal.queryByText('1 of 5 lanes are done')).toBeNull();
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
