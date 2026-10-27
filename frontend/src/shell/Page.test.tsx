import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { REGION_IDS } from './announcer';
import { BOARD, mountShell } from './testing';
import { SAMPLE_FIXTURE } from '../sample/fixture';
import { SAMPLE_FRAGMENT, SAMPLE_HARNESS, SAMPLE_PROJECT, SAMPLE_SID } from '../sample/ids';
import { findSession, sessionTitle } from './derive';

const primary = () => within(screen.getByRole('navigation', { name: 'Primary' }));
const crumb = () =>
  screen
    .queryByRole('navigation', { name: 'Breadcrumb' })
    ?.textContent?.replace(/\s+/g, ' ')
    .trim() ?? null;
const current = () =>
  primary()
    .queryAllByRole('link')
    .find((link) => link.getAttribute('aria-current') === 'page')?.textContent ?? null;

describe('the primary navigation', () => {
  it('lists the four views in the released order with the released labels, each a real link', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const links = primary().getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual([
      'Sessions',
      'Projects',
      'Attention',
      'Intent log',
    ]);
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '#n=sessions',
      '#n=projects',
      '#n=attention',
      '#n=intent',
    ]);
    for (const link of links) expect(link.getAttribute('tabindex')).not.toBe('-1');
  });

  it.each([
    ['#n=sessions', 'Sessions'],
    ['#n=attention', 'Attention'],
    ['#n=projects', 'Projects'],
    ['#n=intent', 'Intent log'],
    ['#n=project:alpha%2Fapp', 'Projects'],
    ['#n=project:alpha%2Fapp:course', 'Projects'],
    ['#n=session:alpha%2Fapp:claude:shared-sid', 'Sessions'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=attention', 'Attention'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=intent', 'Intent log'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=projects', 'Projects'],
    ['#n=session:alpha%2Fapp:claude:shared-sid&from=project', 'Projects'],
    ['#n=bogus', 'Sessions'],
  ])('marks the current location for %s as %s', async (hash, label) => {
    const page = mountShell({ hash, data: BOARD });
    await page.settle();
    expect(current()).toBe(label);
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
    expect(current()).toBe('Attention');
    await page.go('#n=projects');
    expect(current()).toBe('Projects');
    await page.back();
    expect(current()).toBe('Attention');
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
      'Attention › Alpha shared claude',
    ],
    [
      'a session opened from the Intent log',
      '#n=session:alpha%2Fapp:claude:shared-sid&from=intent',
      'Intent log › Alpha shared claude',
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
    ['#n=attention', 'Compass — Attention'],
    ['#n=projects', 'Compass — Projects'],
    ['#n=intent', 'Compass — Intent log'],
    ['#n=project:alpha%2Fapp', 'alpha/app — Compass'],
    ['#n=session:alpha%2Fapp:claude:shared-sid', 'Alpha shared claude — alpha/app — Compass'],
    ['#n=session:beta%2Fapi:claude:colon%3Asid', 'Title not published — beta/api — Compass'],
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
    expect(document.title).toBe('Compass — Attention');
  });
});

describe('the header counts come from the rows the page was given', () => {
  it('reads running and subagents with the legacy sentence, and a reported-block button when a session is blocked', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    expect(document.querySelector('.next-running')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      '● 2 running · 3 subagents observed',
    );
    expect(screen.getByRole('button', { name: '1 reported block' })).toBeInTheDocument();
  });

  it('uses the singular for one subagent and one block, and the plural for any other count', async () => {
    const one = {
      generated: 1,
      sessions: [
        { harness: 'claude', sid: 'a', project: 'p', state: 'needs_input', subagents: [{}] },
      ],
    };
    const page = mountShell({ data: one });
    await page.settle();
    expect(document.querySelector('.next-running')?.textContent).toContain('1 subagent observed');
    expect(screen.getByRole('button', { name: '1 reported block' })).toBeInTheDocument();
    page.unmount();
    const two = {
      generated: 1,
      sessions: [1, 2].map((n) => ({
        harness: 'claude',
        sid: `s${String(n)}`,
        project: 'p',
        state: 'needs_input',
      })),
    };
    const again = mountShell({ data: two });
    await again.settle();
    expect(screen.getByRole('button', { name: '2 reported blocks' })).toBeInTheDocument();
  });

  it('draws no block button when nothing reports a block, and the button leads to Attention', async () => {
    const calm = mountShell({
      data: {
        generated: 1,
        sessions: [{ harness: 'claude', sid: 'a', project: 'p', state: 'idle' }],
      },
    });
    await calm.settle();
    expect(screen.queryByRole('button', { name: /reported block/ })).toBeNull();
    calm.unmount();

    const page = mountShell({ data: BOARD });
    await page.settle();
    fireEvent.click(screen.getByRole('button', { name: '1 reported block' }));
    expect(page.router.getRoute().view).toBe('attention');
    expect(page.history.entries().at(-1)).toBe('#n=attention');
  });

  it('claims no liveness before a board has arrived or when the board carries no session collection', async () => {
    const unread = mountShell({});
    await unread.settle();
    expect(document.querySelector('.next-running')?.textContent).toBe(
      'Waiting for the first board.',
    );
    expect(document.querySelector('.next-status-dot')).toBeNull();
    expect(document.body.textContent).not.toContain('0 running');
    unread.unmount();

    const absent = mountShell({ data: { generated: 1 } });
    await absent.settle();
    expect(document.querySelector('.next-running')?.textContent).toBe(
      'Session data not published.',
    );
    expect(document.body.textContent).not.toContain('0 running');
  });

  it('reads an empty collection as measured zeros, which is a different fact from an absent one', async () => {
    const page = mountShell({ data: { generated: 1, sessions: [] } });
    await page.settle();
    expect(document.querySelector('.next-running')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      '● 0 running · 0 subagents observed',
    );
  });

  it('keeps the counts out of a project page, which has its own More menu with the all-project status', async () => {
    const page = mountShell({ hash: '#n=project:alpha%2Fapp', data: BOARD });
    await page.settle();
    expect(document.querySelector('.next-running')).toBeNull();
    expect(screen.getByText('All projects · 2 running · 3 subagents observed')).toBeInTheDocument();
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
    expect(document.querySelector('.next-running')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      '● 2 running · 3 subagents observed',
    );
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

  it('opens Attention, Projects and Sessions with a, p and s, and ignores the retired dashboard key', async () => {
    expect(await pressed('a', '#n=intent')).toBe('attention');
    expect(await pressed('p', '#n=intent')).toBe('projects');
    expect(await pressed('s', '#n=intent')).toBe('sessions');
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
    fireEvent.keyDown(field, { key: 'a' });
    fireEvent.keyDown(document.body, { key: 'a', ctrlKey: true });
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
