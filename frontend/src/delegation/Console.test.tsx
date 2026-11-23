import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json, mountPanels, type MountOptions } from '../steering/testing';
import { ProjectConsole } from './Console';

/* The Console tab: its order, what its setup line may say about each capability, where the terminal and the
   observer controls sit, and that opening a disclosure is the reader's own and stays open. */
const board = (sessions = 1) => ({
  generated: 1000,
  sessions: [
    { harness: 'claude', sid: 's1', project: 'alpha', state: 'needs_input', title: 'Gate' },
    ...(sessions > 1 ? [{ harness: 'codex', sid: 's2', project: 'alpha', state: 'working' }] : []),
  ],
});
const origin = (state: 'registered' | 'unavailable') => () =>
  json(
    state === 'registered'
      ? { state, origin: { session_name: 'main', window_index: 1, pane_index: 2 } }
      : { state, reason: 'not-registered' },
  );
const context = (observer: boolean | null) => () =>
  json({ semantic: {}, observer_model: observer === null ? null : { enabled: observer } });
const focus = { harness: 'claude', sid: 's1' };
const mount = (
  props: Partial<Parameters<typeof ProjectConsole>[0]> = {},
  options: MountOptions = {},
) =>
  mountPanels(
    <ProjectConsole
      project="alpha"
      projectKey="alpha"
      focus={focus}
      observer={<p data-test="observer-slot">observer controls</p>}
      {...props}
    />,
    { data: board(), routes: { '/api/project-context': context(false) }, ...options },
  );
const summary = (): string =>
  document.querySelector('.next-cockpit-console-setup [data-slot=accordion-trigger]')
    ?.textContent ?? '';
const setup = (): HTMLElement =>
  document.querySelector('.next-cockpit-console-setup') as HTMLElement;
const inside = (selector: string): boolean => setup().querySelector(selector) !== null;

describe('the Console is operations first', () => {
  it('draws the scope, the rail, then the setup, and names the scope exactly', async () => {
    const page = mount(
      {},
      {
        routes: {
          '/api/interaction/origin': origin('unavailable'),
          '/api/project-context': context(false),
        },
      },
    );
    await page.settle();
    const order = [
      ...document.querySelectorAll(
        'header.next-cockpit-scope, aside[data-next-project-rail], .next-cockpit-console-setup',
      ),
    ].map(
      (node) =>
        node.tagName.toLowerCase() +
        (node.classList.contains('next-cockpit-console-setup') ? ':setup' : ''),
    );
    expect(order).toEqual(['header', 'aside', 'div:setup']);
    const cue = document.querySelector('header.next-cockpit-scope .next-scope-cue') as HTMLElement;
    expect(cue.dataset['scopeKind']).toBe('session');
    expect(cue.dataset['scopeOwner']).toBe('claude:s1');
    // A session is selected, so the console does not ask for one.
    expect(screen.queryByText(/Select one exact session/)).toBeNull();
    expect(document.querySelector('[data-next-rail-panel="tripwires"]')).not.toBeNull();
  });

  it('at project scope asks for one exact session, with a way in when there is only one', async () => {
    const page = mount({ focus: null });
    await page.settle();
    expect(
      screen.getByText(/Select one exact session to open its read-only console\./),
    ).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Open this session' }) as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('#n=session:alpha:claude:s1&from=project');
    expect(summary()).toContain('terminal bridge per-session');
  });

  it('offers no way in when several sessions could be meant', async () => {
    const page = mount({ focus: null }, { data: board(2) });
    await page.settle();
    expect(screen.queryByText('Open this session’s console')).toBeNull();
  });
});

describe('what the setup line says about each capability', () => {
  it('says "not read yet" until the registration is read, never "off"', async () => {
    const page = mount(
      {},
      { routes: { '/api/interaction/origin': () => 'hold', '/api/project-context': () => 'hold' } },
    );
    await page.settle();
    expect(summary()).toBe(
      'How this server was started — terminal bridge not read yet, observer model not read yet',
    );
    await page.release('/api/interaction/origin', origin('registered')());
    await page.release('/api/project-context', context(true)());
    expect(summary()).toBe('How this server was started — terminal bridge on, observer model on');
  });

  it('says off for a registration the server refused and a model the server does not offer', async () => {
    const page = mount(
      {},
      {
        routes: {
          '/api/interaction/origin': origin('unavailable'),
          '/api/project-context': context(null),
        },
      },
    );
    await page.settle();
    expect(summary()).toBe('How this server was started — terminal bridge off, observer model off');
  });
});

describe('where the terminal and the observer controls sit', () => {
  it('an enabled capability is operational: outside the setup, after the rail', async () => {
    const page = mount(
      {},
      {
        routes: {
          '/api/interaction/origin': origin('registered'),
          '/api/project-context': context(true),
        },
      },
    );
    await page.settle();
    // Once: a capability placed in both spots would open two terminals and print two sets of controls.
    expect(document.querySelectorAll('[data-next-cockpit-terminal]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-test="observer-slot"]')).toHaveLength(1);
    expect(inside('[data-next-cockpit-terminal]')).toBe(false);
    expect(inside('[data-test="observer-slot"]')).toBe(false);
    expect(document.querySelector('[data-test="observer-slot"]')).not.toBeNull();
    const rail = document.querySelector('aside[data-next-project-rail]') as HTMLElement;
    const terminal = document.querySelector('[data-next-cockpit-terminal]') as HTMLElement;
    expect(rail.compareDocumentPosition(terminal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a disabled one stays behind the setup, closed', async () => {
    const page = mount(
      {},
      {
        routes: {
          '/api/interaction/origin': origin('unavailable'),
          '/api/project-context': context(false),
        },
      },
    );
    await page.settle();
    expect(document.querySelectorAll('[data-next-cockpit-terminal]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-test="observer-slot"]')).toHaveLength(1);
    expect(inside('[data-next-cockpit-terminal]')).toBe(true);
    expect(inside('[data-test="observer-slot"]')).toBe(true);
    expect(setup().hasAttribute('data-open')).toBe(false);
  });

  it('the terminal keeps its place across a poll: a revision that re-reads the registration does not move it', async () => {
    const page = mount(
      {},
      {
        routes: {
          '/api/interaction/origin': origin('registered'),
          '/api/project-context': context(false),
        },
      },
    );
    await page.settle();
    const section = document.querySelector('[data-next-cockpit-terminal]');
    await page.poll({ ...board(), generated: 1001 });
    await page.poll({ ...board(), generated: 1002 });
    expect(document.querySelector('[data-next-cockpit-terminal]')).toBe(section);
    expect(inside('[data-next-cockpit-terminal]')).toBe(false);
  });
});

describe('the setup disclosures are the reader’s', () => {
  it('stay open when opened, across a poll and a return, and are per project and session', async () => {
    const page = mount();
    await page.settle();
    await act(async () => {
      fireEvent.click(setup().querySelector('[data-slot=accordion-trigger]') as HTMLElement);
    });
    await page.poll({ ...board(), generated: 1001 });
    expect(setup().hasAttribute('data-open')).toBe(true);
    page.show(<p>elsewhere</p>);
    page.show(<ProjectConsole project="alpha" projectKey="alpha" focus={focus} />);
    await page.settle();
    expect(setup().hasAttribute('data-open')).toBe(true);
    // Another session of the same project has its own.
    page.show(
      <ProjectConsole project="alpha" projectKey="alpha" focus={{ harness: 'codex', sid: 's2' }} />,
    );
    await page.settle();
    expect(setup().hasAttribute('data-open')).toBe(false);
  });

  it('lists every session of the project exactly, with its state, in the raw status', async () => {
    const page = mount({}, { data: board(2) });
    await page.settle();
    expect(
      [...setup().querySelectorAll('.next-cockpit-console-status li')].map((li) => li.textContent),
    ).toEqual(['claude:s1 · needs_input', 'codex:s2 · working']);
  });
});

describe('nothing is sent', () => {
  it('opens no terminal, starts no model reading and posts nothing', async () => {
    const page = mount(
      {},
      {
        routes: {
          '/api/interaction/origin': origin('registered'),
          '/api/project-context': context(true),
        },
      },
    );
    await page.settle();
    await page.poll({ ...board(), generated: 1001 });
    expect(page.allPosts()).toEqual([]);
    expect(page.state.requests.some((request) => request.url.includes('observer_model=1'))).toBe(
      false,
    );
  });
});
