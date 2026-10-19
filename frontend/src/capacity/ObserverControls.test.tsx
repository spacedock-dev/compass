import { fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ProjectConsole } from '../delegation';
import { json, mountPanels, type Handler, type MountOptions } from '../steering/testing';
import { ObserverControls } from './ObserverControls';

/* Every fetch is counted: the backend is scripted and cannot reach a model. */
const CONSENT = 'compass.observer-model-consent.v1';
const DISCLOSURE = 'Send redacted transcript excerpts for a goal summary? Each prompt is capped.';
const focus = { harness: 'claude', sid: 's1' };
const board = {
  generated: 1000,
  sessions: [{ harness: 'claude', sid: 's1', project: 'alpha', state: 'working', title: 'Work' }],
};
const offer = (over: Record<string, unknown> = {}) => ({
  enabled: true,
  disclosure: DISCLOSURE,
  ...over,
});
const context =
  (model: unknown, extra: Record<string, unknown> = {}): Handler =>
  () =>
    json({ semantic: {}, observer_model: model, ...extra });
const mount = (
  model: unknown,
  options: MountOptions = {},
  props: { focus?: typeof focus | null } = {},
) => {
  const chosen = props.focus === undefined ? focus : props.focus;
  return mountPanels(
    <ProjectConsole
      project="alpha"
      projectKey="alpha"
      focus={chosen}
      observer={<ObserverControls projectKey="alpha" focus={chosen} />}
    />,
    {
      data: board,
      routes: {
        '/api/interaction/origin': () => json({ state: 'unavailable' }),
        '/api/project-context': context(model),
        ...(options.routes ?? {}),
      },
      ...(options.storage ? { storage: options.storage } : {}),
    },
  );
};
const text = (): string =>
  document.querySelector('[data-next-observer-controls]')?.textContent ??
  document.querySelector('.next-cockpit-console-setup .next-cockpit-empty')?.textContent ??
  '';
const modelRequests = (page: ReturnType<typeof mount>) =>
  page.state.requests.filter((r) => /observer_model=1/.test(r.url));
const action = (name: string) =>
  document.querySelector<HTMLButtonElement>(`[data-next-observer-action="${name}"]`);
const press = (name: string) => {
  const button = action(name);
  if (!button) throw new Error(`no ${name} button`);
  fireEvent.click(button);
};

describe('an offer nothing has read is not an offer that is off', () => {
  it('says "not read" before the read arrives, "disabled" after a server that switched it off', async () => {
    const page = mount(offer(), { routes: { '/api/project-context': () => 'hold' as never } });
    await page.settle();
    expect(document.body.textContent).toContain('Observer model availability has not been read.');
    expect(document.body.textContent).not.toContain('disabled for this run');
    await page.release(
      '/api/project-context',
      json({ semantic: {}, observer_model: { enabled: false } }),
    );
    expect(document.body.textContent).toContain('Observer model is disabled for this run.');
    expect(document.body.textContent).toContain('Restart without --no-observer-model');
    expect(document.body.textContent).not.toContain('availability has not been read');
    expect(action('allow')).toBeNull();
    expect(action('request')).toBeNull();
  });

  it('a read that published no offer at all says "not read", as the page did', async () => {
    const page = mount(null);
    await page.settle();
    expect(document.body.textContent).toContain('Observer model availability has not been read.');
    expect(modelRequests(page)).toEqual([]);
  });

  it('an enabled offer with no disclosure withholds the request and says why', async () => {
    const page = mount({ enabled: true });
    await page.settle();
    expect(document.body.textContent).toContain(
      'Observer disclosure is unavailable; model requests are withheld.',
    );
    expect(action('request')).toBeNull();
    expect(action('allow')).toBeNull();
  });

  it('asks for one exact session at project scope, and never offers a display id as one', async () => {
    const page = mount(offer(), {}, { focus: null });
    await page.settle();
    expect(document.body.textContent).toContain(
      'Select one exact session to request an optional model goal summary.',
    );
    page.unmount();
    const half = mount(offer(), {}, { focus: { harness: 'claude', sid: '' } });
    await half.settle();
    expect(action('request')).toBeNull();
    expect(modelRequests(half)).toEqual([]);
  });
});

describe('reader-started goal summaries', () => {
  it.each([undefined, 'declined', 'granted'])(
    'offers a direct request regardless of the retired browser answer (%s)',
    async (answer) => {
      const page = mount(offer(), answer ? { storage: { [CONSENT]: answer } } : {});
      await page.settle();
      expect(text()).toContain(DISCLOSURE);
      expect(action('request')?.textContent).toBe('Summarize this session');
      expect(action('allow')).toBeNull();
      expect(action('decline')).toBeNull();
      await page.poll({ ...board, generated: 1002 });
      expect(modelRequests(page)).toEqual([]);
    },
  );

  it('shows the goal notice and turns readings off with one press', async () => {
    const notice = {
      kind: 'goal',
      provider: 'codex',
      destination: 'goal.example',
      content: 4,
      tool_output: '',
      at: 1000,
    };
    const page = mount(offer(), {
      routes: {
        '/api/project-context': (request) =>
          json({ observer_model: offer(/observer_model=1/.test(request.url) ? { notice } : {}) }),
        '/api/reading': () =>
          json({ ok: true, reading: { consent: false, off: true, reason: 'readings-off' } }),
      },
    });
    await page.settle();
    press('request');
    await page.settle();
    expect(text()).toContain('goal.example');
    const off = document.querySelector<HTMLButtonElement>('[data-next-observer-action="off"]');
    expect(off?.textContent).toBe('Turn off readings');
    fireEvent.click(off as HTMLElement);
    await page.settle();
    expect(
      page.state.requests.filter((r) => r.method === 'POST' && r.path === '/api/reading')[0]?.body,
    ).toEqual({ consent: 'off', press: true, observer_model: 1 });
    expect(text()).toContain('Readings are off.');
    expect(action('request')).toBeNull();
  });

  it('reads a readings-off goal status as off and sends nothing on render', async () => {
    const page = mount(offer(), {
      routes: {
        '/api/project-context': context(offer(), {
          observers: [{ ...focus, model: { status: 'readings-off' } }],
        }),
      },
    });
    await page.settle();
    expect(text()).toContain('Readings are off.');
    expect(action('request')).toBeNull();
    expect(modelRequests(page)).toEqual([]);
  });
});

describe('the one press that starts a model request', () => {
  const allowed = { [CONSENT]: 'granted' };

  it('sends exactly one request for the exact session, shows it in progress, and cannot be doubled', async () => {
    const page = mount(offer(), {
      storage: allowed,
      routes: {
        '/api/project-context': (request) =>
          /observer_model=1/.test(request.url)
            ? 'hold'
            : json({ semantic: {}, observer_model: offer() }),
      },
    });
    await page.settle();
    expect(modelRequests(page)).toEqual([]);
    press('request');
    await page.settle();
    expect(modelRequests(page)).toHaveLength(1);
    const sent = modelRequests(page)[0]?.url ?? '';
    expect(sent).toContain('project=alpha');
    expect(sent).toContain('session=claude%3As1');
    expect(sent).toContain('refresh=1');
    expect(action('request')?.textContent).toBe('Request in progress');
    expect(action('request')?.disabled).toBe(true);
    expect(text()).toContain('The requested model summary is in progress.');
    fireEvent.click(action('request') as HTMLElement);
    expect(modelRequests(page)).toHaveLength(1);
    await page.release(
      '/api/project-context',
      json({
        semantic: {},
        observer_model: offer(),
        observers: [
          { harness: 'claude', sid: 's1', goal: 'Ship the retry queue', model: { status: 'ok' } },
          { harness: 'codex', sid: 's1', goal: 'The other harness' },
        ],
      }),
    );
    expect(text()).toContain('The refresh returned. Model failures fall back to local analysis.');
    expect(text()).toContain('Observed goal: Ship the retry queue');
    expect(text()).toContain('Model status: ok');
    expect(text()).not.toContain('The other harness');
    expect(action('request')?.disabled).toBe(false);
  });

  it('a failed request keeps local analysis and says so', async () => {
    const page = mount(offer(), {
      storage: allowed,
      routes: {
        '/api/project-context': (request) =>
          /observer_model=1/.test(request.url)
            ? new Response('no', { status: 500 })
            : json({ semantic: {}, observer_model: offer() }),
      },
    });
    await page.settle();
    press('request');
    await page.settle();
    expect(text()).toContain('The summary request failed. Local analysis remains available.');
    expect(modelRequests(page)).toHaveLength(1);
  });

  it('says when a refresh returned with no goal, and when the model status was not published', async () => {
    const page = mount(offer(), {
      storage: allowed,
      routes: {
        '/api/project-context': (request) =>
          /observer_model=1/.test(request.url)
            ? json({
                semantic: {},
                observer_model: offer(),
                observers: [{ harness: 'claude', sid: 's1', goal: '  ' }],
              })
            : json({ semantic: {}, observer_model: offer() }),
      },
    });
    await page.settle();
    press('request');
    await page.settle();
    expect(text()).toContain('No goal summary was published by this refresh.');
  });

  it('refuses, and says so, when the offer the board holds is not the one on screen', async () => {
    const page = mount(offer(), { storage: allowed });
    await page.settle();
    const drawn = action('request') as HTMLElement;
    const store = page.shell.runtime.store;
    const key = 'alpha\nclaude:s1';
    const entry = store.getSnapshot().contexts.get(key);
    expect(entry).toBeDefined();
    // The board accepts a different disclosure; the reader's hand is still on the old button. A native click
    // runs the handler this render attached, before React commits the new offer.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    store.setContext(key, {
      ...(entry as NonNullable<typeof entry>),
      data: {
        ...(entry?.data ?? {}),
        observer_model: offer({ disclosure: 'Send everything to another service?' }),
      },
    });
    drawn.click();
    spy.mockRestore();
    await page.settle();
    expect(modelRequests(page)).toEqual([]);
    expect(document.querySelector('[data-next-observer-refused]')?.textContent).toContain(
      'offer changed since this page was drawn',
    );
  });

  it('a reader who leaves while it runs finds the result, and no second request, on return', async () => {
    const hold = (request: { url: string }) =>
      /observer_model=1/.test(request.url)
        ? 'hold'
        : json({ semantic: {}, observer_model: offer() });
    const page = mount(offer(), {
      storage: allowed,
      routes: { '/api/project-context': hold as Handler },
    });
    await page.settle();
    press('request');
    await page.settle();
    page.show(<p>Elsewhere</p>);
    await page.settle();
    await page.release(
      '/api/project-context',
      json({
        semantic: {},
        observer_model: offer(),
        observers: [{ harness: 'claude', sid: 's1', goal: 'Kept goal', model: { status: 'ok' } }],
      }),
    );
    page.show(
      <ProjectConsole
        project="alpha"
        projectKey="alpha"
        focus={focus}
        observer={<ObserverControls projectKey="alpha" focus={focus} />}
      />,
    );
    await page.settle();
    expect(modelRequests(page)).toHaveLength(1);
    expect(text()).toContain('Observed goal: Kept goal');
    expect(page.shell.runtime.store.getSnapshot().observer.requests).toEqual([]);
  });
});
