import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ShellContext } from './context';
import { ProjectTabs } from './ProjectTabs';
import { BOARD, mountShell } from './testing';

/* A tab's accessible name carries its cue ("Course 0 No observed state changes observed"), so a tab is found by its label. */
const tab = (name: string) => screen.getByRole('tab', { name: new RegExp(`^${name}`) });
const hash = (page: ReturnType<typeof mountShell>) => page.history.entries().at(-1);

async function open(fragment: string) {
  const page = mountShell({ hash: fragment, data: BOARD });
  await page.settle();
  return page;
}

describe('the project tab strip', () => {
  it('draws four tabs with Now selected by default and only the selected one in the tab order', async () => {
    await open('#n=project:alpha%2Fapp');
    expect(
      screen
        .getAllByRole('tab')
        .map((node) => [
          node.firstChild?.textContent,
          node.getAttribute('aria-selected'),
          node.getAttribute('tabindex'),
        ]),
    ).toEqual([
      ['Now', 'true', '0'],
      ['Course', 'false', '-1'],
      ['Decisions', 'false', '-1'],
      ['Console', 'false', '-1'],
    ]);
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
    expect(screen.getByRole('tablist').getAttribute('aria-label')).toBe('Project cockpit views');
  });

  it('selects the tab the route names, and keeps a focused session across tab changes', async () => {
    const page = await open('#n=project:alpha%2Fapp:claude%3Ashared-sid:console');
    expect(tab('Console').getAttribute('aria-selected')).toBe('true');
    fireEvent.click(tab('Course'));
    expect(hash(page)).toBe('#n=project:alpha%2Fapp:claude%3Ashared-sid:course');
  });

  it('wraps over the strip with the arrow keys and puts focus on the tab it selects', async () => {
    const page = await open('#n=project:alpha%2Fapp');
    act(() => tab('Now').focus());
    await act(async () => fireEvent.keyDown(tab('Now'), { key: 'ArrowLeft' }));
    expect(hash(page)).toBe('#n=project:alpha%2Fapp:console');
    expect(document.activeElement).toBe(tab('Console'));
    await act(async () => fireEvent.keyDown(tab('Console'), { key: 'ArrowRight' }));
    expect(hash(page)).toBe('#n=project:alpha%2Fapp');
    expect(document.activeElement).toBe(tab('Now'));
    await act(async () => fireEvent.keyDown(tab('Now'), { key: 'ArrowRight' }));
    expect(hash(page)).toBe('#n=project:alpha%2Fapp:course');
  });

  it('jumps to the ends with Home and End', async () => {
    const page = await open('#n=project:alpha%2Fapp:decisions');
    await act(async () => fireEvent.keyDown(tab('Decisions'), { key: 'End' }));
    expect(hash(page)).toBe('#n=project:alpha%2Fapp:console');
    await act(async () => fireEvent.keyDown(tab('Console'), { key: 'Home' }));
    expect(hash(page)).toBe('#n=project:alpha%2Fapp');
  });

  it.each([
    { key: 'End', start: '', focused: 'Console', target: 'Console', suffix: ':console' },
    { key: 'Home', start: ':console', focused: 'Now', target: 'Now', suffix: '' },
    { key: 'ArrowRight', start: '', focused: 'Console', target: 'Now', suffix: '' },
    { key: 'ArrowLeft', start: ':console', focused: 'Now', target: 'Console', suffix: ':console' },
  ])(
    'activates $key after Back leaves focus on $focused',
    async ({ key, start, focused, target, suffix }) => {
      const page = await open(`#n=project:alpha%2Fapp${start}`);
      act(() => tab(focused).focus());
      expect(tab(focused).getAttribute('aria-selected')).toBe('true');
      await page.back();
      expect(page.history.env.getHash()).toBe(`#n=project:alpha%2Fapp${start}`);
      expect(document.activeElement).toBe(tab(focused));
      expect(tab(focused).getAttribute('aria-selected')).toBe('false');

      let notCancelled = true;
      await act(async () => {
        notCancelled = fireEvent.keyDown(tab(focused), { key });
      });
      expect(page.history.env.getHash()).toBe(`#n=project:alpha%2Fapp${suffix}`);
      expect(notCancelled).toBe(false);
      expect(document.activeElement).toBe(tab(target));
      expect(tab(target).getAttribute('aria-selected')).toBe('true');
      expect(tab(target).getAttribute('tabindex')).toBe('0');
    },
  );

  it('leaves a modified arrow or Home/End to the browser, as the legacy page does', async () => {
    const page = await open('#n=project:alpha%2Fapp');
    const before = page.history.entries().length;
    for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
      for (const modifier of [{ altKey: true }, { metaKey: true }, { ctrlKey: true }]) {
        const notCancelled = fireEvent.keyDown(tab('Now'), { key, ...modifier });
        expect(notCancelled, `${key} ${Object.keys(modifier)[0]} must not be cancelled`).toBe(true);
      }
    }
    expect(page.history.entries()).toHaveLength(before);
    expect(hash(page)).toBe('#n=project:alpha%2Fapp');
  });

  it('leaves every other key to the browser', async () => {
    const page = await open('#n=project:alpha%2Fapp');
    const before = page.history.entries().length;
    for (const key of ['Enter', 'ArrowUp', 'z', 'Tab']) fireEvent.keyDown(tab('Now'), { key });
    expect(page.history.entries().length).toBe(before);
  });

  it('names the panel for the tab that is current, and draws what the tab holds inside it', async () => {
    await open('#n=project:alpha%2Fapp:course');
    const panel = screen.getByRole('tabpanel');
    const tabId = tab('Course').getAttribute('id');
    expect(panel.getAttribute('id')).toMatch(/^next-cockpit-\d+-panel-course$/);
    expect(panel.getAttribute('aria-labelledby')).toBe(tabId);
    expect(tab('Course').getAttribute('aria-controls')).toBe(panel.getAttribute('id'));
    expect(panel.querySelector('[data-next-cockpit-panel="course"]')).not.toBeNull();
    expect(panel.textContent).not.toMatch(/DRC-/);
  });

  it('draws the steering step in the Decisions and Console tabs, with no placeholder left standing', async () => {
    for (const name of ['decisions', 'console']) {
      const page = await open(`#n=project:alpha%2Fapp:${name}`);
      const panel = screen.getByRole('tabpanel');
      expect(panel.querySelector('[data-next-placeholder]')).toBeNull();
      expect(panel.textContent).not.toMatch(/DRC-/);
      expect(panel.textContent?.trim().length).toBeGreaterThan(0);
      page.unmount();
    }
  });

  it('gives each mounted strip its own ids, so every ARIA reference in the document resolves to one element', async () => {
    const page = await open('#n=project:alpha%2Fapp:course');
    const route = page.router.getRoute();
    if (route.view !== 'project') throw new Error('the fixture route is not a project view');
    // A second project view beside the first, in the same document and under the same shell: the page as it
    // is when two views are mounted at once. The shell's own regions are page singletons and stay once.
    const second = render(
      <ShellContext.Provider value={page.shell}>
        <ProjectTabs route={{ ...route, tab: 'decisions' }}>{(tab) => <p>{tab}</p>}</ProjectTabs>
      </ShellContext.Provider>,
    );
    expect(screen.getAllByRole('tablist')).toHaveLength(2);
    expect(screen.getAllByRole('tabpanel')).toHaveLength(2);

    const ids = [...document.querySelectorAll('[id]')].map((node) => node.id);
    expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([]);

    const refs = [...document.querySelectorAll('[aria-controls], [aria-labelledby]')].flatMap(
      (node) =>
        ['aria-controls', 'aria-labelledby']
          .map((attr) => node.getAttribute(attr))
          .filter((value): value is string => value !== null)
          .flatMap((value) => value.split(/\s+/)),
    );
    expect(refs.length).toBeGreaterThan(0);
    for (const ref of refs) {
      const matches = ids.filter((id) => id === ref);
      expect(matches, `reference ${ref}`).toHaveLength(1);
    }
    second.unmount();
  });
});
