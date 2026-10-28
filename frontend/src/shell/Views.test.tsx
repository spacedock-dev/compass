import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BOARD, mountShell } from './testing';

async function open(fragment: string, data: unknown = BOARD) {
  const page = mountShell({ hash: fragment, data });
  await page.settle();
  return page;
}

describe('every top-level view is drawn by its own screen', () => {
  it('draws Attention itself, with no stated slot standing in for it', async () => {
    await open('#n=attention');
    expect(document.querySelector('[data-next-placeholder]')).toBeNull();
    expect(document.querySelector('[data-next-view-body="attention"]')).not.toBeNull();
    expect(document.querySelector('[data-next-attention-section="risk"]')).not.toBeNull();
    expect(document.body.textContent).not.toContain('not available in the React interface yet');
  });

  it('draws the Projects list and a project page themselves, with a stated slot only where the steering step is still to come', async () => {
    await open('#n=projects');
    expect(document.querySelector('[data-next-placeholder]')).toBeNull();
    expect(document.querySelectorAll('article.next-project-row').length).toBeGreaterThan(0);
    await open('#n=project:alpha%2Fapp');
    expect(document.querySelector('article.next-project-detail')).not.toBeNull();
    expect(document.querySelector('[data-next-placeholder]')).toBeNull();
  });

  it('draws the Sessions screen, the session page, the Intent panel and the drift reading themselves, with no stated slot left', async () => {
    await open('#n=sessions');
    expect(document.querySelector('[data-next-placeholder]')).toBeNull();
    expect(document.querySelectorAll('article.next-operation-row')).toHaveLength(
      BOARD.sessions.length,
    );
    await open('#n=session:alpha%2Fapp:claude:shared-sid');
    expect(document.querySelector('article.next-session-detail')).not.toBeNull();
    expect(document.querySelector('[data-next-placeholder]')).toBeNull();
    expect(document.querySelector('.next-session-drift')).not.toBeNull();
  });

  it('draws Settings from its own read, before and without a board', async () => {
    const page = await open('#n=settings', null);
    expect(document.querySelector('[data-next-view-body="settings"]')).not.toBeNull();
    expect(page.backend.requests).toContainEqual({ method: 'GET', url: '/api/settings' });
    // With no board this scripted backend answers nothing, so the read fails and says so.
    expect(screen.getByText('The settings could not be read, so none are shown.')).toBeTruthy();
  });
});

describe('an absent source is stated as absent', () => {
  it('says the first payload has not arrived, on every route, before one has', () => {
    // Read straight after mounting, before the boot read has answered either way.
    for (const fragment of [
      '#n=sessions',
      '#n=project:alpha%2Fapp',
      '#n=session:alpha%2Fapp:claude:shared-sid',
    ]) {
      const page = mountShell({ hash: fragment, data: BOARD });
      expect(screen.getByText('The first payload has not arrived yet.')).toBeInTheDocument();
      expect(document.body.textContent).not.toContain('Not present in the current payload');
      expect(document.body.textContent).not.toContain('This session is not in the current payload');
      page.unmount();
    }
  });

  it('says no data has been received once reads have failed and none has ever succeeded', async () => {
    const page = await open('#n=sessions', null);
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(screen.getByText('No data has been received in this tab.')).toBeInTheDocument();
  });

  it('says a board with no session collection published none, rather than that a project is missing from it', async () => {
    await open('#n=project:alpha%2Fapp', { generated: 1 });
    expect(screen.getByText('The board published no session collection.')).toBeInTheDocument();
  });
});

describe('a project route', () => {
  it('states a project the board does not hold, with the way to all projects', async () => {
    const page = await open('#n=project:nowhere');
    expect(screen.getByText('Not present in the current payload.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'View all projects' }));
    expect(page.router.getRoute().view).toBe('projects');
  });

  it('states a stale session filter and links to the project root, keeping the tab', async () => {
    const page = await open('#n=project:alpha%2Fapp:claude%3Agone:course');
    expect(screen.getByText('Session filter is outside this payload window')).toBeInTheDocument();
    expect(screen.getByText('claude:gone')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View project root' }).getAttribute('href')).toBe(
      '#n=project:alpha%2Fapp:course',
    );
    fireEvent.click(screen.getByRole('link', { name: 'View project root' }));
    await page.settle();
    expect(page.router.getRoute()).toMatchObject({ view: 'project', project: 'alpha/app' });
  });

  it('matches a focused session by its exact key, the sid under the other harness being another session', async () => {
    const held = await open('#n=project:alpha%2Fapp:codex%3Ashared-sid');
    expect(screen.queryByText('Session filter is outside this payload window')).toBeNull();
    held.unmount();
    await open('#n=project:beta%2Fapi:codex%3Ashared-sid');
    expect(screen.getByText('Session filter is outside this payload window')).toBeInTheDocument();
  });

  it('keeps an empty-project sid’s project route out of reach, since an empty project is not a project', async () => {
    const page = await open('#n=project:');
    expect(page.router.getRoute().view).toBe('sessions');
  });
});

describe('a session route', () => {
  it('names a session the board does not hold, by its harness and sid, with the hours the board holds', async () => {
    await open('#n=session:alpha%2Fapp:claude:gone', { ...BOARD, window_hours: 24 });
    expect(screen.getByText('This session is not in the current payload.')).toBeInTheDocument();
    expect(screen.getByText('claude · gone')).toBeInTheDocument();
    expect(
      screen.getByText('The board holds sessions observed in the last 24 hours.'),
    ).toBeInTheDocument();
    expect(
      document.querySelector('[data-next-session-state]')?.getAttribute('data-next-session-state'),
    ).toBe('outside-payload');
  });

  it('says one hour in the singular and nothing about a window the board did not state', async () => {
    const one = await open('#n=session:alpha%2Fapp:claude:gone', { ...BOARD, window_hours: 1 });
    expect(
      screen.getByText('The board holds sessions observed in the last 1 hour.'),
    ).toBeInTheDocument();
    one.unmount();
    await open('#n=session:alpha%2Fapp:claude:gone');
    expect(document.body.textContent).not.toContain('The board holds sessions');
  });

  it('refuses the released id-only form when two harnesses carry the sid, and opens it when one does', async () => {
    const ambiguous = await open('#n=session:alpha%2Fapp:shared-sid');
    expect(screen.getByText('This session is not in the current payload.')).toBeInTheDocument();
    ambiguous.unmount();
    await open('#n=session:beta%2Fapi:colon%3Asid');
    expect(screen.queryByText('This session is not in the current payload.')).toBeNull();
  });

  it('opens a session with no project label, which is a real group', async () => {
    await open('#n=session::codex:bare-project-sid');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('No project label');
  });

  it('titles the page with the published title or the sentence that says there is none', async () => {
    await open('#n=session:beta%2Fapi:claude:colon%3Asid');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Title not published');
  });

  it('links back to Sessions from an absent session, and the link goes through the router', async () => {
    const page = await open('#n=session:alpha%2Fapp:claude:gone');
    fireEvent.click(screen.getByRole('link', { name: 'View all sessions' }));
    expect(page.router.getRoute().view).toBe('sessions');
  });
});

describe('a link to a route', () => {
  it('leaves a modified click to the browser and a plain click to the router', async () => {
    const page = await open('#n=session:alpha%2Fapp:claude:gone');
    const link = screen.getByRole('link', { name: 'View all sessions' });
    expect(link.getAttribute('href')).toBe('#n=sessions');
    fireEvent.click(link, { ctrlKey: true });
    expect(page.router.getRoute().view).toBe('session');
    fireEvent.click(link, { button: 1 });
    expect(page.router.getRoute().view).toBe('session');
  });
});
