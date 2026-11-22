// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PROJECT_TABS, TOP_LEVEL_VIEWS } from '../router/grammar';
import { BOARD, mountShell } from '../shell/testing';
import { GLOSSARY } from './glossary';

describe('the first-layer glossary', () => {
  it('matches every row of the design record in order', () => {
    const design = readFileSync('docs/design-calm-compass.md', 'utf8');
    const glossary = design.split(/^## /m).find((section) => /^Glossary\r?\n/.test(section));
    if (!glossary) throw new Error('The design record has no Glossary section.');
    const rows = glossary
      .split(/\r?\n/)
      .filter((line) => line.startsWith('|'))
      .slice(2)
      .map((row) =>
        row
          .slice(1, -1)
          .split('|')
          .map((cell) => cell.trim()),
      );

    expect(rows).toEqual(
      Object.values(GLOSSARY).map(({ plain, replaces, technical, distinctFrom, exceptions }) => [
        plain,
        replaces,
        technical,
        distinctFrom,
        exceptions,
      ]),
    );
  });

  it('has no open rows and keeps the Needs you navigation name', () => {
    expect(Object.values(GLOSSARY).filter(({ status }) => status === 'open')).toEqual([]);
    expect(GLOSSARY.attention.plain).toBe('Needs you');
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
        navigation.getByRole('link', { name: label, current: 'page' }).getAttribute('href'),
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
    expect(tabs.getAllByRole('tab')).toHaveLength(PROJECT_TABS.length);
    for (const tab of PROJECT_TABS) {
      const label = GLOSSARY[tab].shown;
      const trigger = tabs.getByRole('tab', { name: (name) => name.startsWith(label) });
      expect(trigger.getAttribute('data-arg')).toBe(tab);
    }
  });

  it('uses the fallback crumb before a session can be found and keeps the ID in the title', () => {
    mountShell({ hash: '#n=session:alpha%2Fapp:claude:missing' });
    const crumb = within(screen.getByRole('navigation', { name: GLOSSARY.breadcrumb.shown }));
    expect(crumb.getByText(GLOSSARY.session.shown).getAttribute('aria-current')).toBe('page');
    expect(screen.getByText(GLOSSARY.waitingForBoard.shown)).toBeVisible();
    expect(document.title).toBe(['missing', 'alpha/app', GLOSSARY.compass.shown].join(' — '));
  });
});
