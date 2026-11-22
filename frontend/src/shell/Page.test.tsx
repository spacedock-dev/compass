import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { REGION_IDS } from './announcer';
import { headerBoard } from '../../test/headerBoard';
import { BOARD, mountShell } from './testing';
import { SAMPLE_FIXTURE } from '../sample/fixture';
import { SAMPLE_FRAGMENT, SAMPLE_HARNESS, SAMPLE_PROJECT, SAMPLE_SID } from '../sample/ids';
import { findSession, sessionTitle } from './derive';

const primary = () => within(screen.getByRole('navigation', { name: 'Primary' }));
const crumb = () => {
  const nav = screen.queryByRole('navigation', { name: 'Breadcrumb' });
  if (!nav) return null;
  return [...nav.querySelectorAll('a, [aria-current="page"]')]
    .map((segment) => segment.textContent?.trim())
    .join(' › ');
};
const current = () => primary().getByRole('link', { current: 'page' });
const working = () => screen.getByRole('status', { name: 'Working sessions' });

describe('the primary navigation', () => {
  it('lists the five views in order with their plain labels, each a real link', async () => {
    const page = mountShell({ data: headerBoard() });
    await page.settle();
    const links = primary().getAllByRole('link');
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '#n=sessions',
      '#n=projects',
      '#n=attention',
      '#n=intent',
      '#n=settings',
    ]);
    expect(primary().getByRole('link', { name: 'Needs you 3' })).toBe(links[2]);
    expect(primary().getByRole('link', { name: 'Goal history' })).toBe(links[3]);
    expect(screen.getByRole('link', { name: 'Compass' }).getAttribute('href')).toBe('#n=sessions');
    for (const link of links) expect(link.getAttribute('tabindex')).not.toBe('-1');
  });

  it.each([
    ['#n=sessions', 'Sessions'],
    ['#n=attention', 'Needs you'],
    ['#n=projects', 'Projects'],
    ['#n=intent', 'Goal history'],
    ['#n=settings', 'Settings'],
    ['#n=project:alpha%2Fapp', 'Projects'],
    ['#n=project:alpha%2Fapp:course', 'Projects'],
    ['#n=session:alpha%2Fapp:claude:shared-sid', 'Sessions'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=attention', 'Needs you'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=intent', 'Goal history'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=projects', 'Projects'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=project', 'Projects'],
    ['#n=bogus', 'Sessions'],
  ])('marks the current location for %s as %s', async (hash, label) => {
    const page = mountShell({ hash, data: BOARD });
    await page.settle();
    expect(
      primary().getByRole('link', {
        name: label === 'Needs you' ? 'Needs you 1' : label,
        current: 'page',
      }),
    ).toBe(current());
    expect(
      primary()
        .getAllByRole('link')
        .filter((link) => link.getAttribute('aria-current') === 'page'),
    ).toHaveLength(1);
  });

  it('follows a link from one view to the next and keeps Back honest', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    await page.go('#n=attention');
    expect(primary().getByRole('link', { name: 'Needs you 1', current: 'page' })).toBe(current());
    await page.go('#n=projects');
    expect(primary().getByRole('link', { name: 'Projects', current: 'page' })).toBe(current());
    await page.back();
    expect(primary().getByRole('link', { name: 'Needs you 1', current: 'page' })).toBe(current());
  });
});

describe('the breadcrumb', () => {
  it('is absent on every top-level view', async () => {
    for (const hash of ['#n=sessions', '#n=attention', '#n=projects', '#n=intent']) {
      const page = mountShell({ hash, data: BOARD });
      await page.settle();
      expect(crumb(), hash).toBeNull();
      page.unmount();
    }
  });

  it.each([
    ['a project page', '#n=project:alpha%2Fapp', 'Projects › alpha/app'],
    [
      'a session opened from nowhere',
      '#n=session:alpha%2Fapp:claude:shared-sid',
      'Sessions › Alpha shared claude',
    ],
    [
      'the same sid under the other harness',
      '#n=session:alpha%2Fapp:codex:shared-sid',
      'Sessions › Alpha shared codex',
    ],
    [
      'a session with no published title',
      '#n=session:beta%2Fapi:claude:colon%3Asid',
      'Sessions › Title not published',
    ],
    [
      'a session opened from Attention',
      '#n=session:alpha%2Fapp:claude:shared-sid&from=attention',
      'Needs you › Alpha shared claude',
    ],
    [
      'a session opened from the Goal history',
      '#n=session:alpha%2Fapp:claude:shared-sid&from=intent',
      'Goal history › Alpha shared claude',
    ],
    [
      'a session opened from a project',
      '#n=session:alpha%2Fapp:claude:shared-sid&from=project',
      'Projects › alpha/app › Alpha shared claude',
    ],
    [
      'a project-less session opened from Projects',
      '#n=session::codex:bare-project-sid&from=projects',
      'Projects › No project label',
    ],
    [
      'a session the board does not hold',
      '#n=session:alpha%2Fapp:claude:missing',
      'Sessions › Session',
    ],
  ])('reads %s', async (_name, hash, text) => {
    const page = mountShell({ hash, data: BOARD });
    await page.settle();
    expect(crumb()).toBe(text);
  });

  it('marks the current segment and links every earlier one', async () => {
    const page = mountShell({
      hash: '#n=session:alpha%2Fapp:claude:shared-sid&from=project',
      data: BOARD,
    });
    await page.settle();
    const nav = within(screen.getByRole('navigation', { name: 'Breadcrumb' }));
    expect(
      nav.getAllByRole('link').map((link) => [link.textContent, link.getAttribute('href')]),
    ).toEqual([
      ['Projects', '#n=projects'],
      ['alpha/app', '#n=project:alpha%2Fapp'],
    ]);
    expect(nav.getByText('Alpha shared claude').getAttribute('aria-current')).toBe('page');
    expect(
      screen
        .getByRole('navigation', { name: 'Breadcrumb' })
        .querySelectorAll('svg[data-icon="caret-right"]'),
    ).toHaveLength(2);
  });

  it('says "Session" for a session it cannot find before the first board, claiming nothing about a board nobody has read', async () => {
    const page = mountShell({ hash: '#n=session:alpha%2Fapp:claude:shared-sid' });
    await page.settle();
    expect(crumb()).toBe('Sessions › Session');
  });

  it('names the sample session by its title, read from the sample’s own board, in the crumb and the tab', async () => {
    const page = mountShell({ hash: SAMPLE_FRAGMENT, data: BOARD });
    await page.settle();
    const title = sessionTitle(
      findSession(
        SAMPLE_FIXTURE.board as never,
        SAMPLE_PROJECT,
        SAMPLE_HARNESS,
        SAMPLE_SID,
      ) as never,
    );
    expect(title).not.toBe('');
    expect(crumb()).toBe(`Sessions › ${title}`);
    expect(document.title.startsWith(`${title} — `)).toBe(true);
  });
});

describe('the document title is one per view and does not move while the board refreshes', () => {
  it.each([
    ['#n=sessions', 'Compass — Sessions'],
    ['#n=attention', 'Compass — Needs you'],
    ['#n=projects', 'Compass — Projects'],
    ['#n=intent', 'Compass — Goal history'],
    ['#n=settings', 'Compass — Settings'],
    ['#n=project:alpha%2Fapp', 'alpha/app — Compass'],
    ['#n=session:alpha%2Fapp:claude:shared-sid', 'Alpha shared claude — alpha/app — Compass'],
    // This fixture session waits on you, so its tab says so first.
    [
      '#n=session:beta%2Fapi:claude:colon%3Asid',
      '● Needs you · Title not published — beta/api — Compass',
    ],
    // The released id-only link names no harness and still opens that one session, so its tab says so too.
    ['#n=session:beta%2Fapi:colon%3Asid', '● Needs you · Title not published — beta/api — Compass'],
    // An empty project leaves two dashes side by side, which `document.title` collapses to one space, as the legacy page's does.
    ['#n=session::codex:bare-project-sid', 'No project label — — Compass'],
  ])('%s is titled %s', async (hash, title) => {
    const page = mountShell({ hash, data: BOARD });
    await page.settle();
    expect(document.title).toBe(title);
  });

  it('names a session the board does not hold by its own id, never an invented title', async () => {
    const page = mountShell({ hash: '#n=session:alpha%2Fapp:claude:missing', data: BOARD });
    await page.settle();
    expect(document.title).toBe('missing — alpha/app — Compass');
  });

  it('keeps the title through a refresh and changes it with the route', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const seen = new Set<string>();
    for (let poll = 0; poll < 3; poll += 1) {
      await act(async () => {
        await page.shell.runtime.refresh();
      });
      seen.add(document.title);
    }
    expect([...seen]).toEqual(['Compass — Sessions']);
    await page.go('#n=attention');
    expect(document.title).toBe('Compass — Needs you');
  });
});

describe('the header counts come from the displayed board', () => {
  it('shows the same all-board Working count through every view, even without event liveness', async () => {
    const page = mountShell({ data: headerBoard() });
    await page.settle();
    for (const fragment of [
      '#n=sessions',
      '#n=projects',
      '#n=attention',
      '#n=intent',
      '#n=settings',
      '#n=project:acme%2Fdashboard',
      '#n=session:acme%2Fdashboard:claude:active',
    ]) {
      await page.go(fragment);
      expect(working().textContent, fragment).toBe('2 sessions working');
    }
  });

  it('uses the singular when exactly one session displays Working', async () => {
    const data = headerBoard();
    const page = mountShell({ data: { ...data, sessions: data.sessions.slice(0, 1) } });
    await page.settle();
    expect(working().textContent).toBe('1 session working');
  });

  it('counts the native wait with an exact request once and includes Worth a look but not a clean end', async () => {
    const page = mountShell({ data: headerBoard() });
    await page.settle();
    expect(primary().getByRole('link', { name: 'Needs you 3' }).getAttribute('href')).toBe(
      '#n=attention',
    );
    expect(screen.queryByRole('button', { name: /reported blocks?/ })).toBeNull();
    await page.go('#n=attention');
    expect(primary().getByRole('link', { name: 'Needs you 3', current: 'page' })).toBe(current());
    expect(screen.getByRole('heading', { level: 1, name: 'Needs you' })).toBeVisible();
    expect(screen.getByText('Approve the command?')).toBeVisible();
    const waiting = screen.getByRole('heading', { name: 'Needs you now (2)' }).closest('section');
    if (!waiting) throw new Error('The waiting section is missing');
    const links = within(waiting).getAllByRole('link');
    expect(
      links.filter((link) => link.getAttribute('href')?.includes(':claude:gate')),
    ).toHaveLength(1);
  });

  it('claims no Working count or badge before a board, or without a published collection', async () => {
    const unread = mountShell({});
    await unread.settle();
    expect(working().textContent).toBe('Waiting for the first board.');
    expect(primary().getByRole('link', { name: 'Needs you' })).toBeVisible();
    unread.unmount();

    const absent = mountShell({ data: { generated: 1 } });
    await absent.settle();
    expect(working().textContent).toBe('Session data not published.');
    expect(primary().getByRole('link', { name: 'Needs you' })).toBeVisible();
  });

  it('reports a measured zero on an empty board', async () => {
    const page = mountShell({ data: { generated: 1, sessions: [] } });
    await page.settle();
    expect(working().textContent).toBe('Nothing working right now');
    expect(primary().getByRole('link', { name: 'Needs you' })).toBeVisible();
  });

  it('keeps project More actions available without a duplicate fleet count', async () => {
    const page = mountShell({ hash: '#n=project:alpha%2Fapp', data: BOARD });
    await page.settle();
    expect(working().textContent).toBe('2 sessions working');
    expect(screen.getByText('More', { selector: 'summary' })).toBeVisible();
    expect(screen.queryByText(/subagents? observed/)).toBeNull();
  });
});

describe('a failed refresh', () => {
  it('shows nothing at one failure and a notice at two, and the next success clears it', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    page.backend.failing = true;
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(screen.queryByText(/Live refresh failed/)).toBeNull();
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(screen.getByText('Live refresh failed twice in a row.')).toBeInTheDocument();
    expect(
      screen.getByText(
        /Displayed data may be stale\. Last updated 0s ago\. Retrying automatically every 20s\./,
      ),
    ).toBeInTheDocument();
    page.backend.failing = false;
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(screen.queryByText(/Live refresh failed/)).toBeNull();
  });

  it('keeps the rows on screen while it fails, and says so rather than showing an empty healthy board', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    page.backend.failing = true;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      await act(async () => {
        await page.shell.runtime.refresh();
      });
    }
    expect(working().textContent).toBe('2 sessions working');
    expect(screen.getByText('Live refresh failed 3 times in a row.')).toBeInTheDocument();
  });

  it('retries once per press, and not at all on mount', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    page.backend.failing = true;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await act(async () => {
        await page.shell.runtime.refresh();
      });
    }
    const before = page.gets();
    page.backend.failing = false;
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry now' }));
      await flush();
    });
    expect(page.gets()).toBe(before + 1);
  });
});

async function flush() {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
}

describe('a newer build and a reset history', () => {
  it('asks for a reload when the server was restarted into another build, and reloads only on the press', async () => {
    const page = mountShell({ data: { ...BOARD, build: 'b1' } });
    await page.settle();
    page.backend.data = { ...BOARD, build: 'b2' };
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(screen.getByText('Reload to use the new version.')).toBeInTheDocument();
    expect(page.reload).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(page.reload).toHaveBeenCalledTimes(1);
  });

  it('names a history reset by which reset it was', async () => {
    const page = mountShell({ data: { ...BOARD, history_reset: 'unreadable' } });
    await page.settle();
    expect(screen.getByText('The saved history was reset.')).toBeInTheDocument();
    expect(document.body.textContent).toContain('The saved file could not be read.');
  });
});

describe('the keyboard', () => {
  /* The route after one key, from a page of its own that is gone afterwards: two mounted pages would both
     hear the one window event, and the first would take the key before the second saw it. */
  async function pressed(key: string, hash: string, init: KeyboardEventInit = {}) {
    const page = mountShell({ hash, data: BOARD });
    await page.settle();
    await act(async () => {
      fireEvent.keyDown(document.body, { key, ...init });
      await flush();
    });
    const view = page.router.getRoute().view;
    page.unmount();
    return view;
  }

  it('opens Needs you, Projects and Sessions with n, p and s and leaves retired keys alone', async () => {
    expect(await pressed('n', '#n=intent')).toBe('attention');
    expect(await pressed('p', '#n=intent')).toBe('projects');
    expect(await pressed('s', '#n=intent')).toBe('sessions');
    expect(await pressed('a', '#n=intent')).toBe('intent');
    expect(await pressed('h', '#n=intent')).toBe('intent');
    expect(await pressed('d', '#n=intent')).toBe('intent');
  });

  it('walks a session back to where it was opened from with Escape, and a project back to Sessions', async () => {
    expect(await pressed('Escape', '#n=session:alpha%2Fapp:claude:shared-sid&from=attention')).toBe(
      'attention',
    );
    expect(await pressed('Escape', '#n=project:alpha%2Fapp')).toBe('sessions');
  });

  it('does nothing over a form field or with a modifier held', async () => {
    const page = mountShell({ hash: '#n=intent', data: BOARD });
    await page.settle();
    const field = document.createElement('input');
    document.body.append(field);
    fireEvent.keyDown(field, { key: 'n' });
    fireEvent.keyDown(document.body, { key: 'n', ctrlKey: true });
    expect(page.router.getRoute().view).toBe('intent');
    field.remove();
  });
});

describe('the page is React’s alone and starts nothing on its own', () => {
  it('reads the board once, opens one stream and sends no POST, although StrictMode runs every effect twice', async () => {
    const page = mountShell({ data: BOARD, strict: true });
    await page.settle();
    expect(page.gets()).toBe(1);
    expect(page.env.streamOpens()).toBe(1);
    expect(page.env.openStreams()).toBe(1);
    expect(page.posts()).toBe(0);
    // The board read carries `usage=1`, since the quota fetch is on until turned off; nothing else is asked.
    expect(page.backend.requests.filter((r) => r.url.split('?')[0] !== '/api/data')).toEqual([]);
  });

  it('stops the board’s resources when the page unmounts', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    page.unmount();
    await act(async () => {
      page.clock.advance(1);
      await flush();
    });
    expect(page.env.openStreams()).toBe(0);
  });

  it('draws each of the five live regions exactly once, empty, beside the replaceable page and not inside it', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const app = document.getElementById('app');
    expect(app).not.toBeNull();
    for (const id of Object.values(REGION_IDS)) {
      expect(document.querySelectorAll(`#${id}`)).toHaveLength(1);
      expect(app?.contains(document.getElementById(id))).toBe(false);
      expect(document.getElementById(id)?.textContent).toBe('');
    }
    expect(document.querySelectorAll('[role="alert"]')).toHaveLength(1);
  });

  it('keeps the same region nodes, and a sentence written to one, across a change of route', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const cue = document.getElementById(REGION_IDS.cue);
    act(() => page.shell.announcer.announce('save:goal', 'Saved.'));
    await page.go('#n=attention');
    await page.go('#n=project:alpha%2Fapp');
    expect(document.getElementById(REGION_IDS.cue)).toBe(cue);
    expect(cue?.textContent).toBe('Saved.');
  });

  it('never builds a text selection or a range of its own: selection is the browser’s, and nothing restores one', () => {
    const offenders: string[] = [];
    const walk = (directory: string) => {
      for (const name of readdirSync(directory)) {
        const path = join(directory, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (
          /\.(ts|tsx)$/.test(name) &&
          !/\.test\./.test(name) &&
          !/(testing\.tsx?|\.helper\.ts)$/.test(name)
        ) {
          const text = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
          if (/getSelection|createRange|addRange|selectAllChildren|setBaseAndExtent/.test(text))
            offenders.push(path);
        }
      }
    };
    walk(resolve(process.cwd(), 'frontend/src'));
    expect(offenders).toEqual([]);
  });

  it('never writes markup into the document from a string: no innerHTML, no insertAdjacentHTML, no document.write', () => {
    const root = resolve(process.cwd(), 'frontend/src');
    const offenders: string[] = [];
    const walk = (directory: string) => {
      for (const name of readdirSync(directory)) {
        const path = join(directory, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (
          /\.(ts|tsx)$/.test(name) &&
          !/\.test\./.test(name) &&
          !/testing\.tsx?$/.test(name)
        ) {
          const text = readFileSync(path, 'utf8');
          if (
            /innerHTML|outerHTML|insertAdjacentHTML|dangerouslySetInnerHTML|document\.write/.test(
              text.replace(/\/\*[\s\S]*?\*\//g, ''),
            )
          )
            offenders.push(path);
        }
      }
    };
    walk(root);
    expect(offenders).toEqual([]);
  });
});
