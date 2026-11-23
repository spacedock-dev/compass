import { act, fireEvent, render } from '@testing-library/react';
import { StrictMode, useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FetchLike } from '../api/client';
import { ControlsProvider } from '../controls/ControlsProvider';
import { fakeBackend, type FakeBackend } from '../../test/storage_backends';
import { ShellContext } from '../shell/context';
import { createShell } from '../shell/createShell';
import { createFakeClock, createFakeEnvironment } from '../transport/testing';
import { Timeline } from './Timeline';

/* The Decisions panel over the real shell objects and a scripted backend: the context reads, the filter
   store, the disclosure store and the display gate are the real ones. */

const TASK = 'workflow:project-cockpit';
const FOCUS = { harness: 'codex', sid: 'focus-1' };

const SEMANTIC = {
  facts: [
    {
      fact_id: 'fo-a',
      at: 104,
      type: 'user_message',
      summary: 'Newest direction',
      source_session: FOCUS,
      evidence: { source: 'root transcript', confidence: 'exact' },
    },
    {
      fact_id: 'task-a',
      at: 103,
      type: 'prepared_dispatch',
      summary: 'Dispatch cockpit',
      source_session: FOCUS,
      work_item_id: TASK,
      evidence: { source: 'dispatch artifact', confidence: 'exact' },
    },
    {
      fact_id: 'fo-b',
      at: 102,
      type: 'user_message',
      summary: 'Correct the lane order',
      source_session: FOCUS,
      evidence: { source: 'root transcript', confidence: 'exact' },
    },
    {
      fact_id: 'task-b',
      at: 101,
      type: 'stage_transition',
      stage: 'shaping',
      summary: 'Shaping cockpit',
      work_item_id: TASK,
      evidence: { source: 'workflow state', confidence: 'exact' },
    },
    {
      fact_id: 'gate-a',
      at: 100,
      type: 'gate_decision',
      source_kind: 'gate',
      summary: 'project-cockpit · review · approve',
      scope: 'project',
      by: 'person:captain',
      decision: 'approve',
      stage: 'review',
      application_state: 'consumed',
      target_stage: 'shaping',
      work_item_id: TASK,
      evidence: { source: 'entity gate', confidence: 'exact' },
    },
  ],
  work_items: [{ work_item_id: TASK, label: 'project-cockpit', kind: 'workflow_item' }],
  relations: [
    {
      type: 'dispatches_to',
      from: 'fo:codex:focus-1',
      to: `task:${TASK}`,
      evidence_ref: 'task-a',
      confidence: 'exact',
    },
  ],
  projections: {
    operator_intents: [
      { projection_id: 'intent-a', at: 104, summary: 'Newest direction', derived_from: 'fo-a' },
      {
        projection_id: 'intent-b',
        at: 102,
        summary: 'Correct the lane order',
        derived_from: 'fo-b',
      },
    ],
    steering_episodes: [],
    trail_heads: [
      {
        work_item_id: TASK,
        status: 'current stage',
        stage: 'shaping',
        latest_meaningful_event: 'task-b',
      },
    ],
    activity: { nodes: [{ kind: 'work', at: 103, work_item_ids: [TASK] }] },
  },
  history: { window_sec: 86400, events: [] },
};

interface Script {
  semantic: unknown;
  failing: boolean;
  generated: number;
}

function world(options: { backend?: FakeBackend; script?: Partial<Script> } = {}) {
  const script: Script = { semantic: SEMANTIC, failing: false, generated: 1000, ...options.script };
  const backend = options.backend ?? fakeBackend();
  const clock = createFakeClock();
  const env = createFakeEnvironment({ clock });
  const requests: { method: string; url: string }[] = [];
  const fetch: FetchLike = (url, init) => {
    requests.push({ method: init?.method ?? 'GET', url });
    if (url.startsWith('/api/data')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            generated: script.generated,
            sessions: [],
            harnesses: [{ key: 'codex', label: 'Codex' }],
          }),
          { status: 200, headers: { 'X-Compass-Revision': `r${String(script.generated)}` } },
        ),
      );
    }
    if (url.startsWith('/api/project-context')) {
      if (script.failing) return Promise.resolve(new Response('{}', { status: 500 }));
      return Promise.resolve(
        new Response(
          JSON.stringify({ semantic: script.semantic, observers: [], child_assignments: [] }),
          { status: 200 },
        ),
      );
    }
    return Promise.reject(new Error('offline'));
  };
  const shell = createShell({
    env,
    fetch,
    provider: () => backend,
    events: { addEventListener: () => undefined, removeEventListener: () => undefined },
    search: '',
    doc: null,
    reducedMotion: () => true,
  });
  return { shell, backend, requests, script, release: shell.runtime.acquire() };
}

const settle = () =>
  act(async () => {
    for (let turn = 0; turn < 16; turn += 1) await Promise.resolve();
  });

interface MountProps {
  project?: string;
  focus?: boolean;
  defaultMode?: 'decisions';
}

function mount(w: ReturnType<typeof world>, props: MountProps = {}) {
  const project = props.project ?? 'alpha/app';
  const focus = props.focus === false ? null : { ...FOCUS, state: 'idle' };
  const Host = () => {
    const [shown, setShown] = useState(true);
    return (
      <>
        <button type="button" onClick={() => setShown((value) => !value)}>
          toggle view
        </button>
        {shown ? (
          <Timeline
            project={project}
            projectKey={`${project}-key`}
            focus={focus}
            sessions={[FOCUS]}
            {...(props.defaultMode ? { defaultMode: props.defaultMode } : {})}
          />
        ) : (
          <p>another view</p>
        )}
      </>
    );
  };
  return render(
    <StrictMode>
      <ShellContext value={w.shell}>
        <ControlsProvider controls={w.shell.controls}>
          <Host />
        </ControlsProvider>
      </ShellContext>
    </StrictMode>,
  );
}

/* A poll through the runtime, so the display gate paints it as it would a real one. */
const refresh = (w: ReturnType<typeof world>) =>
  act(async () => {
    await w.shell.runtime.refresh({ manual: true });
  });

const ids = (container: HTMLElement) =>
  [...container.querySelectorAll('article[data-event-id]')].map((row) =>
    row.getAttribute('data-event-id'),
  );

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (run: () => void) => setTimeout(run, 0));
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('reading the semantic context', () => {
  it('says it is loading, then shows the events, having made two passive reads and no other request', async () => {
    const w = world();
    const view = mount(w);
    expect(view.getByText('Loading semantic context…')).toBeInTheDocument();
    await settle();
    expect(ids(view.container).length).toBeGreaterThan(0);
    const reads = w.requests.filter((request) => request.url.startsWith('/api/project-context'));
    expect(reads.map((request) => request.method)).toEqual(['GET', 'GET']);
    expect(reads.map((request) => request.url).sort()).toEqual(
      [
        '/api/project-context?project=alpha%2Fapp-key',
        '/api/project-context?project=alpha%2Fapp-key&session=codex%3Afocus-1',
      ].sort(),
    );
    expect(w.requests.filter((request) => request.method !== 'GET')).toEqual([]);
    w.release();
  });

  it('says the context is unavailable, not empty, when the read failed', async () => {
    const w = world({ script: { failing: true } });
    const view = mount(w);
    await settle();
    expect(view.getByText('Semantic context unavailable.')).toBeInTheDocument();
    expect(ids(view.container)).toEqual([]);
    w.release();
  });

  it('keeps the last rows and says the refresh failed when a later read fails', async () => {
    const w = world();
    const view = mount(w);
    await settle();
    const before = ids(view.container);
    w.script.failing = true;
    w.script.generated = 2000;
    await refresh(w);
    expect(ids(view.container)).toEqual(before);
    const notice = view.container.querySelector('[data-next-cockpit-stale-read]');
    expect(notice?.textContent).toMatch(
      /^Last read \d\d:\d\d\. Refresh has failed since; these are the rows from that read\.$/,
    );
    w.release();
  });

  it('states the empty window the payload published, and not a count it did not measure', async () => {
    const w = world({
      script: {
        semantic: {
          facts: [],
          work_items: [],
          relations: [],
          projections: {},
          history: { window_sec: 7200, events: [] },
        },
      },
    });
    const view = mount(w, { defaultMode: 'decisions' });
    await settle();
    expect(view.getByText('No decisions observed in the last 2 hours.')).toBeInTheDocument();
    w.release();
  });

  it('says the history window was not published when it was not', async () => {
    const w = world({ script: { semantic: { facts: [], projections: {} } } });
    const view = mount(w);
    await settle();
    expect(
      view.getByText(
        'No semantic events for active work available. The semantic history window was not published.',
      ),
    ).toBeInTheDocument();
    w.release();
  });
});

describe('the activity filter', () => {
  it('opens on the caller’s default and on Active otherwise, with the pressed state on one button', async () => {
    const w = world();
    const decisions = mount(w, { defaultMode: 'decisions' });
    await settle();
    expect(decisions.getByRole('heading', { name: 'Recorded decisions' })).toBeInTheDocument();
    expect(decisions.getByRole('button', { name: 'Decisions' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    expect(
      decisions.getByRole('button', { name: 'Current work' }).getAttribute('aria-pressed'),
    ).toBe('false');
    expect(ids(decisions.container)).toEqual(['gate-a']);
    decisions.unmount();
    const active = mount(w);
    await settle();
    expect(active.getByRole('heading', { name: 'Activity timeline' })).toBeInTheDocument();
    expect(active.getByRole('button', { name: 'Current work' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    expect(active.getByRole('group', { name: 'Work activity filter' })).toBeInTheDocument();
    w.release();
  });

  it('shows more in All events than in Active, and writes only the one released map', async () => {
    const w = world();
    const view = mount(w);
    await settle();
    const active = ids(view.container);
    fireEvent.click(view.getByRole('button', { name: 'All events' }));
    const all = ids(view.container);
    expect(all.length).toBeGreaterThanOrEqual(active.length);
    expect(view.getByRole('button', { name: 'All events' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    // The runtime's own leader lease is not this panel's; the panel's one write is the filter map.
    expect(w.backend.writes.filter((key) => key !== 'compass.next.leader')).toEqual([
      'compass.next.graph.mode',
    ]);
    expect(w.backend.data.get('compass.next.graph.mode')).toBe(
      '{"alpha/app\\u0000codex:focus-1":"all"}',
    );
    w.release();
  });

  it('keeps its focus on the button the reader pressed', async () => {
    const w = world();
    const view = mount(w);
    await settle();
    const button = view.getByRole('button', { name: 'Decisions' });
    button.focus();
    fireEvent.click(button);
    expect(document.activeElement).toBe(button);
    expect(view.getByRole('button', { name: 'Decisions' })).toBe(button);
    w.release();
  });

  it('survives leaving and coming back, a reload, and keeps sibling projects and sessions independent', async () => {
    const backend = fakeBackend();
    const first = world({ backend });
    const view = mount(first, { project: 'alpha/app' });
    await settle();
    fireEvent.click(view.getByRole('button', { name: 'Decisions' }));
    fireEvent.click(view.getByRole('button', { name: 'toggle view' }));
    fireEvent.click(view.getByRole('button', { name: 'toggle view' }));
    expect(view.getByRole('button', { name: 'Decisions' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    view.unmount();
    // A sibling project, same session identity: untouched.
    const sibling = mount(first, { project: 'beta/api' });
    await settle();
    expect(sibling.getByRole('button', { name: 'Current work' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    sibling.unmount();
    // The same project at project scope, with no session focused: its own choice.
    const projectScope = mount(first, { project: 'alpha/app', focus: false });
    await settle();
    expect(
      projectScope.getByRole('button', { name: 'Current work' }).getAttribute('aria-pressed'),
    ).toBe('true');
    projectScope.unmount();
    first.release();
    // A reload: a new shell over the same browser storage.
    const second = world({ backend });
    const reloaded = mount(second, { project: 'alpha/app' });
    await settle();
    expect(reloaded.getByRole('button', { name: 'Decisions' }).getAttribute('aria-pressed')).toBe(
      'true',
    );
    second.release();
  });
});

describe('disclosures', () => {
  const open = (details: HTMLElement) => {
    act(() => {
      (details.querySelector('[data-slot=accordion-trigger]') as HTMLElement).click();
    });
    return act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
  };

  it('keeps an opened event open, on the same node, across a live update', async () => {
    const w = world();
    const view = mount(w);
    await settle();
    const row = view.container.querySelector('article[data-event-id="fo-a"]');
    const details = row?.querySelector('[data-slot=accordion]') as HTMLElement;
    await open(details);
    w.script.generated = 2000;
    await refresh(w);
    const after = view.container.querySelector(
      'article[data-event-id="fo-a"] [data-slot=accordion]',
    ) as HTMLElement;
    expect(after).toBe(details);
    expect(after.hasAttribute('data-open')).toBe(true);
    w.release();
  });

  it('keeps an opened event open after leaving and coming back, and not for another project', async () => {
    const w = world();
    const view = mount(w, { project: 'alpha/app' });
    await settle();
    await open(
      view.container.querySelector(
        'article[data-event-id="fo-a"] [data-slot=accordion]',
      ) as HTMLElement,
    );
    fireEvent.click(view.getByRole('button', { name: 'toggle view' }));
    fireEvent.click(view.getByRole('button', { name: 'toggle view' }));
    expect(
      (
        view.container.querySelector(
          'article[data-event-id="fo-a"] [data-slot=accordion]',
        ) as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(true);
    // Only that event: another in the same list did not open with it.
    expect(
      (
        view.container.querySelector(
          'article[data-event-id="fo-b"] [data-slot=accordion]',
        ) as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(false);
    view.unmount();
    const other = mount(w, { project: 'beta/api' });
    await settle();
    expect(
      (
        other.container.querySelector(
          'article[data-event-id="fo-a"] [data-slot=accordion]',
        ) as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(false);
    w.release();
  });

  it('keeps project scope and a focused session apart, so neither inherits the other’s open event', async () => {
    const w = world();
    const focused = mount(w, { project: 'alpha/app' });
    await settle();
    await open(
      focused.container.querySelector(
        'article[data-event-id="fo-a"] [data-slot=accordion]',
      ) as HTMLElement,
    );
    focused.unmount();
    const projectScope = mount(w, { project: 'alpha/app', focus: false });
    await settle();
    expect(
      (
        projectScope.container.querySelector(
          'article[data-event-id="fo-a"] [data-slot=accordion]',
        ) as HTMLElement
      ).hasAttribute('data-open'),
    ).toBe(false);
    w.release();
  });

  it('registers each summary under its own focus key, at project scope as at session scope', async () => {
    const w = world();
    const project = mount(w, { project: 'alpha/app', focus: false });
    await settle();
    const lane = w.shell.controls.focusLane;
    expect(lane.focus('substrate:project:alpha/app\ntimeline-event:fo-a')).toBe(true);
    expect(document.activeElement?.tagName).toBe('BUTTON');
    expect(document.activeElement?.closest('article')?.getAttribute('data-event-id')).toBe('fo-a');
    project.unmount();
    const session = mount(w, { project: 'alpha/app' });
    await settle();
    expect(lane.focus('substrate:project:alpha/app\ntimeline-event:fo-a')).toBe(false);
    expect(lane.focus('substrate:codex:focus-1\ntimeline-event:fo-a')).toBe(true);
    expect(document.activeElement?.closest('article')?.getAttribute('data-event-id')).toBe('fo-a');
    session.unmount();
    w.release();
  });

  it('shows the evidence behind an event, naming what was not published rather than leaving it blank', async () => {
    const semantic = {
      ...SEMANTIC,
      facts: [
        {
          fact_id: 'bare',
          at: 'x',
          type: 'user_message',
          summary: 'A direction with no evidence',
          source_session: FOCUS,
        },
      ],
      projections: {
        operator_intents: [
          {
            projection_id: 'i',
            at: 1,
            summary: 'A direction with no evidence',
            derived_from: 'bare',
          },
        ],
      },
    };
    const w = world({ script: { semantic } });
    const view = mount(w);
    await settle();
    const text = view.container.querySelector('article[data-event-id="bare"]')?.textContent ?? '';
    expect(text).toContain('Evidence source not published.');
    expect(text).toContain('Evidence confidence not published.');
    expect(text).toContain('Event time not published.');
    w.release();
  });

  it('folds directions past the fifth into an Earlier meaningful disclosure', async () => {
    const facts = Array.from({ length: 8 }, (_, index) => ({
      fact_id: `d${String(index)}`,
      at: 200 - index * 3600,
      type: 'user_message',
      summary: `Distinct direction number ${String(index)} about ${['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel'][index] ?? ''}`,
      source_session: FOCUS,
    }));
    const semantic = {
      facts,
      work_items: [],
      projections: {
        operator_intents: facts.map((fact, index) => ({
          projection_id: `i${String(index)}`,
          at: fact.at,
          summary: fact.summary,
          derived_from: fact.fact_id,
        })),
      },
    };
    const w = world({ script: { semantic } });
    const view = mount(w);
    await settle();
    const band = view.getByText('Earlier meaningful · 3');
    expect(band.tagName).toBe('BUTTON');
    expect(
      band.closest('[data-slot=accordion]')?.querySelectorAll('article[data-event-id]'),
    ).toHaveLength(3);
    w.release();
  });
});
