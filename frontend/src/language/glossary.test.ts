// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PROJECT_TABS, TOP_LEVEL_VIEWS } from '../router/grammar';
import { BOARD, mountShell } from '../shell/testing';
import { documentTitle } from '../shell/title';
import { GLOSSARY, SHOWN } from './glossary';

// Keep the real record for agreement checks and give shell tests a replaceable copy of its wording.
vi.mock(import('./glossary'), async (load) => {
  const glossary = await load();
  return { ...glossary, SHOWN: { ...glossary.SHOWN } };
});

const released = { ...SHOWN };
afterEach(() => {
  Object.assign(SHOWN, released);
});

const tabLabel = (tab: HTMLElement): string =>
  Array.from(tab.childNodes)
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent)
    .join('');

function designColumns(design: string): string[][] {
  const glossary = design.split(/^## /m).find((section) => /^Glossary\r?\n/.test(section));
  if (!glossary) throw new Error('The design record has no Glossary section.');
  const tables = glossary
    .split(/\r?\n[ \t]*\r?\n/)
    .map((block) => block.split(/\r?\n/))
    .filter(([, separator]) => /^\|(?:\s*:?-+:?\s*\|){5}$/.test(separator?.trim() ?? ''));
  const [table] = tables;
  if (!table || tables.length !== 1) throw new Error('Expected one five-column glossary table.');
  return table.slice(2).map((row) => {
    const cells = row
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((cell) => cell.trim());
    if (cells.length !== 5) throw new Error(`Expected five glossary cells in: ${row}`);
    return cells;
  });
}

const design = readFileSync('docs/design-calm-compass.md', 'utf8');
const moduleColumns = Object.values(GLOSSARY).map(
  ({ plain, replaces, technical, distinctFrom, exceptions }) => [
    plain,
    replaces,
    technical,
    distinctFrom,
    exceptions,
  ],
);

describe('the first-layer glossary', () => {
  it('matches every row of the design record in order', () => {
    expect(designColumns(design)).toEqual(moduleColumns);
  });

  it('rejects a rendered record-only row with leading indentation', () => {
    const extra = '| Extra control | old | detail | separate | none |';
    const mutated = design.replace(/^(?=\| Project cockpit views \|)/m, `  ${extra}\n`);
    expect(designColumns(mutated)).not.toEqual(moduleColumns);
  });

  it('has no open rows and keeps the Needs you navigation name', () => {
    expect(Object.values(GLOSSARY).filter(({ status }) => status === 'open')).toEqual([]);
    expect(GLOSSARY.attention.plain).toBe('Needs you');
  });

  it('includes the six controls and sections named in the owner record', () => {
    const words = Object.values(GLOSSARY).map(({ plain }) => plain);
    expect(words).toEqual(
      expect.arrayContaining([
        'Dismiss',
        'Mark as read',
        'Steer back',
        'Use your prompt',
        'Edit goal',
        'Your data',
      ]),
    );
  });

  it('uses the ruled goal-edit button text', () => {
    expect(GLOSSARY.updateGoalInstead).toMatchObject({
      plain: 'Update my goal instead',
      shown: 'Update my goal instead',
    });
  });
});

describe('the labels the shell shows today', () => {
  it('uses the same view labels in the primary navigation, titles, and session breadcrumbs', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    expect(screen.getByText(GLOSSARY.compass.shown, { exact: true })).toBeVisible();
    const navigation = within(screen.getByRole('navigation', { name: GLOSSARY.primary.shown }));
    expect(navigation.getAllByRole('link')).toHaveLength(TOP_LEVEL_VIEWS.length);

    for (const view of TOP_LEVEL_VIEWS) {
      const label = GLOSSARY[view].shown;
      await page.go('#n=' + view);
      expect(
        navigation
          .getByRole('link', { name: view === 'attention' ? label + ' 1' : label, current: 'page' })
          .getAttribute('href'),
      ).toBe('#n=' + view);
      expect(document.title).toBe([GLOSSARY.compass.shown, label].join(' — '));

      await page.go('#n=session:alpha%2Fapp:claude:shared-sid&from=' + view);
      const crumb = within(screen.getByRole('navigation', { name: GLOSSARY.breadcrumb.shown }));
      const home = view === 'settings' ? 'sessions' : view;
      expect(crumb.getByRole('link', { name: GLOSSARY[home].shown }).getAttribute('href')).toBe(
        '#n=' + home,
      );
      expect(crumb.getByText('Alpha shared claude').getAttribute('aria-current')).toBe('page');
      expect(document.title).toBe(
        ['Alpha shared claude', 'alpha/app', GLOSSARY.compass.shown].join(' — '),
      );
    }
  });

  it('keeps the project name in the breadcrumb and title and labels the released tabs', async () => {
    const page = mountShell({ hash: '#n=project:alpha%2Fapp', data: BOARD });
    await page.settle();
    const crumb = within(screen.getByRole('navigation', { name: GLOSSARY.breadcrumb.shown }));
    expect(crumb.getByRole('link', { name: GLOSSARY.projects.shown }).getAttribute('href')).toBe(
      '#n=projects',
    );
    expect(crumb.getByText('alpha/app').getAttribute('aria-current')).toBe('page');
    expect(document.title).toBe(['alpha/app', GLOSSARY.compass.shown].join(' — '));

    const tabs = within(screen.getByRole('tablist', { name: GLOSSARY.projectTabs.shown }));
    const triggers = tabs.getAllByRole('tab');
    expect(triggers.map((tab) => tab.getAttribute('data-arg'))).toEqual(PROJECT_TABS);
    expect(triggers.map(tabLabel)).toEqual(PROJECT_TABS.map((tab) => GLOSSARY[tab].shown));
  });

  it('uses the fallback crumb before a session can be found and keeps the ID in the title', () => {
    mountShell({ hash: '#n=session:alpha%2Fapp:claude:missing' });
    const crumb = within(screen.getByRole('navigation', { name: GLOSSARY.breadcrumb.shown }));
    expect(crumb.getByText(GLOSSARY.session.shown).getAttribute('aria-current')).toBe('page');
    expect(screen.getByText(GLOSSARY.waitingForBoard.shown)).toBeVisible();
    expect(document.title).toBe(['missing', 'alpha/app', GLOSSARY.compass.shown].join(' — '));
  });

  it('renders substituted glossary labels in navigation, breadcrumbs, project tabs and titles', async () => {
    const labels = {
      compass: 'Test board',
      primary: 'Test main navigation',
      breadcrumb: 'Test trail',
      sessions: 'Test work list',
      projects: 'Test project list',
      attention: 'Test requests',
      intent: 'Test goal archive',
      settings: 'Test preferences',
      help: 'Test guide',
      session: 'Test missing session',
      projectTabs: 'Test project views',
      now: 'Test current activity',
      course: 'Test direction changes',
      decisions: 'Test decisions',
      console: 'Test terminal',
      waitingForBoard: 'Test board waiting',
    };
    Object.assign(SHOWN, labels);
    const page = mountShell({ data: BOARD });
    expect(screen.getByText(labels.waitingForBoard)).toBeVisible();
    await page.settle();
    expect(screen.getByText(labels.compass, { exact: true })).toBeVisible();
    const navigation = within(screen.getByRole('navigation', { name: labels.primary }));
    for (const view of TOP_LEVEL_VIEWS) {
      await page.go('#n=' + view);
      expect(
        navigation.getByRole('link', {
          name: view === 'attention' ? labels.attention + ' 1' : labels[view],
          current: 'page',
        }),
      ).toBeVisible();
      expect(document.title).toBe(`${labels.compass} — ${labels[view]}`);
    }

    await page.go('#n=project:alpha%2Fapp');
    const tabs = within(screen.getByRole('tablist', { name: labels.projectTabs }));
    expect(tabs.getAllByRole('tab').map(tabLabel)).toEqual(PROJECT_TABS.map((tab) => labels[tab]));
    const projectTrail = within(screen.getByRole('navigation', { name: labels.breadcrumb }));
    expect(projectTrail.getByRole('link', { name: labels.projects })).toBeVisible();
    expect(projectTrail.getByText('alpha/app')).toBeVisible();
    expect(document.title).toBe(`alpha/app — ${labels.compass}`);

    await page.go('#n=session:alpha%2Fapp:claude:missing&from=intent');
    const sessionTrail = within(screen.getByRole('navigation', { name: labels.breadcrumb }));
    expect(sessionTrail.getByRole('link', { name: labels.intent })).toBeVisible();
    expect(sessionTrail.getByText(labels.session).getAttribute('aria-current')).toBe('page');
    expect(document.title).toBe(`missing — alpha/app — ${labels.compass}`);
  });

  it('uses the absent-sessions label after a board arrives without the collection', async () => {
    const page = mountShell({ data: { generated: 1 } });
    const header = within(screen.getByRole('banner'));
    expect(header.getByText(GLOSSARY.waitingForBoard.shown)).toBeVisible();
    await page.settle();
    expect(header.getByText(GLOSSARY.sessionDataNotPublished.shown)).toBeVisible();

    Object.assign(SHOWN, { sessionDataNotPublished: 'Test session collection absent' });
    await page.go('#n=projects');
    expect(header.getByText('Test session collection absent')).toBeVisible();
  });

  it('uses the glossary Session fallback when the title receives an empty session ID', () => {
    const route = { view: 'session', project: 'beta/api', session: '' } as const;
    expect(documentTitle(route, null)).toBe(`${GLOSSARY.session.shown} — beta/api — Compass`);
    Object.assign(SHOWN, { session: 'Test missing ID' });
    expect(documentTitle(route, null)).toBe('Test missing ID — beta/api — Compass');
  });

  it.each([
    [false, 'Test missing title'],
    [true, 'Test command-only title'],
  ])(
    'uses glossary wording for the waiting title and untitled fallback (command: %s)',
    async (command, fallback) => {
      Object.assign(SHOWN, {
        waitingTitle: '● Test needs a reply ·',
        titleNotPublished: 'Test missing title',
        commandOnlyTitle: 'Test command-only title',
      });
      const data = {
        ...BOARD,
        sessions: BOARD.sessions.map((row) =>
          row.sid === 'colon:sid' ? { ...row, first_prompt_control: command } : row,
        ),
      };
      await mountShell({ hash: '#n=session:beta%2Fapi:claude:colon%3Asid', data }).settle();
      const trail = within(screen.getByRole('navigation', { name: GLOSSARY.breadcrumb.shown }));
      expect.soft(trail.queryByText(fallback, { selector: '[aria-current="page"]' })).toBeVisible();
      expect(document.title).toBe(`● Test needs a reply · ${fallback} — beta/api — Compass`);
    },
  );

  it.each([
    [0, 'Test nothing in motion'],
    [1, '1 session in motion'],
    [2, '2 sessions in motion'],
  ])('uses glossary wording with a measured Working count of %i', async (count, label) => {
    Object.assign(SHOWN, {
      workingSessions: 'Test current work',
      workingCountOne: '{count} session in motion',
      workingCountMany: '{count} sessions in motion',
      nothingWorking: 'Test nothing in motion',
    });
    const sessions = BOARD.sessions.filter(({ state }) => state === 'working').slice(0, count);
    await mountShell({ data: { ...BOARD, sessions } }).settle();
    expect(screen.getByRole('status', { name: 'Test current work' }).textContent).toBe(label);
  });
});
