import { act, fireEvent, render } from '@testing-library/react';
import { StrictMode, useState, type ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlsProvider } from './ControlsProvider';
import { Disclosure } from './Disclosure';
import { disclosureKey } from './disclosureStore';
import { createDisclosureBinding } from './useDisclosureState';
import { testControls, type TestControlsOptions } from './testControls';

function mount(ui: ReactElement, options: TestControlsOptions = {}) {
  const kit = testControls(options);
  const wrap = (node: ReactElement) => (
    <StrictMode>
      <ControlsProvider controls={kit.controls}>{node}</ControlsProvider>
    </StrictMode>
  );
  const view = render(wrap(ui));
  return { kit, view, rerender: (node: ReactElement) => view.rerender(wrap(node)) };
}

const key = (name: string, project: string | null = 'alpha', scope: string | null = 'claude:s1') =>
  disclosureKey({ project, scope, name });

function isOpen(node: HTMLElement | null) {
  return node instanceof HTMLDetailsElement
    ? node.open
    : (node?.hasAttribute('data-open') ?? false);
}

function toggle(details: HTMLElement, open: boolean) {
  if (!(details instanceof HTMLDetailsElement)) {
    if (isOpen(details) !== open)
      fireEvent.click(details.querySelector('[data-slot=accordion-trigger]') as HTMLElement);
    return;
  }
  // jsdom queues its own `toggle` event; the component listens for exactly that one.
  act(() => {
    details.open = open;
  });
}

const flushToggle = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));

describe('a disclosure keeps its open state by key, not by node', () => {
  beforeEach(() => {
    // After the click's own activation behaviour has opened the node, as a real frame is.
    vi.stubGlobal('requestAnimationFrame', (run: () => void) => setTimeout(run, 0));
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('follows a store write made outside React, without remounting', async () => {
    const { view, kit, rerender } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        Body
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    act(() => kit.controls.disclosures.set(key('plan'), true));
    expect(isOpen(details)).toBe(true);
    await flushToggle();
    act(() => kit.controls.disclosures.set(key('plan'), false));
    rerender(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        Poll
      </Disclosure>,
    );
    await flushToggle();
    expect(isOpen(details)).toBe(false);
    expect(view.getByText('Project plan').closest('[data-slot=accordion],details')).toBe(details);
  });

  it('records a summary opening before a poll and its queued toggle', async () => {
    const { view, kit, rerender } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        Body
      </Disclosure>,
    );
    fireEvent.click(view.getByText('Project plan'));
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(true);
    rerender(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        Poll
      </Disclosure>,
    );
    await flushToggle();
    expect(
      isOpen(
        view
          .getByText('Project plan')
          .closest('[data-slot=accordion],details') as HTMLDetailsElement,
      ),
    ).toBe(true);
  });

  it('ignores a queued native opening superseded by newer external writes', async () => {
    const { view, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan" variant="menu">
        Body
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(details, true);
    act(() => kit.controls.disclosures.set(key('plan'), true));
    act(() => kit.controls.disclosures.set(key('plan'), false));
    const stale = new Event('toggle');
    Object.defineProperty(stale, 'newState', { value: 'open' });
    fireEvent(details, stale);
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(false);
    await flushToggle();
    expect(isOpen(details)).toBe(false);
  });

  it('accepts a native opening after a write that landed before the subscription', () => {
    const { controls } = testControls();
    const store = controls.disclosures;
    const binding = createDisclosureBinding(store, key('plan'));
    const details = document.createElement('details');
    const detach = binding.attach(details);
    // The parent's layout effect closes the section before the passive subscribe runs.
    store.set(key('plan'), false);
    const release = binding.subscribe(vi.fn());
    details.open = true;
    const opening = new Event('toggle');
    Object.defineProperty(opening, 'newState', { value: 'open' });
    binding.toggle(opening);
    expect(store.isOpen(key('plan'))).toBe(true);
    release();
    detach();
  });

  it('lets an external close supersede a native opening while the store is still closed', async () => {
    const { view, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan" variant="menu">
        Body
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(details, true);
    act(() => kit.controls.disclosures.set(key('plan'), false));
    const stale = new Event('toggle');
    Object.defineProperty(stale, 'newState', { value: 'open' });
    fireEvent(details, stale);
    await flushToggle();
    expect(isOpen(details)).toBe(false);
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(false);
  });

  it('closes a native opening on a summary press before its queued toggle', async () => {
    const { view, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan" variant="menu">
        Body
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(details, true);
    fireEvent.click(view.getByText('Project plan'));
    await flushToggle();
    expect(isOpen(details)).toBe(false);
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(false);
  });

  it('never echoes a toggle caused by rendering a store write', async () => {
    const { view, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        Body
      </Disclosure>,
    );
    const set = vi.spyOn(kit.controls.disclosures, 'set');
    act(() => kit.controls.disclosures.set(key('plan'), true));
    await flushToggle();
    expect(
      isOpen(
        view
          .getByText('Project plan')
          .closest('[data-slot=accordion],details') as HTMLDetailsElement,
      ),
    ).toBe(true);
    expect(set).toHaveBeenCalledTimes(1);
  });

  it('keeps the latest rapid press and lets siblings open together', async () => {
    const { view, kit } = mount(
      <>
        <Disclosure disclosureKey={key('a')} summary="A">
          A body
        </Disclosure>
        <Disclosure disclosureKey={key('b')} summary="B">
          B body
        </Disclosure>
      </>,
    );
    for (let i = 0; i < 3; i += 1) fireEvent.click(view.getByText('A'));
    fireEvent.click(view.getByText('B'));
    expect(kit.controls.disclosures.isOpen(key('a'))).toBe(true);
    expect(kit.controls.disclosures.isOpen(key('b'))).toBe(true);
    await flushToggle();
    expect(
      isOpen(view.getByText('A').closest('[data-slot=accordion],details') as HTMLDetailsElement),
    ).toBe(true);
    expect(
      isOpen(view.getByText('B').closest('[data-slot=accordion],details') as HTMLDetailsElement),
    ).toBe(true);
  });

  it('accepts a native browser opening even when a redraw precedes the queued event', async () => {
    const { view, kit, rerender } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan" variant="menu">
        Body
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(details, true);
    rerender(
      <Disclosure disclosureKey={key('plan')} summary="Project plan" variant="menu">
        Poll
      </Disclosure>,
    );
    await flushToggle();
    expect(isOpen(details)).toBe(true);
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(true);
  });

  it('publishes a browser beforematch opening through the controlled store and retains it across a redraw', () => {
    const { view, kit, rerender } = mount(
      <Disclosure disclosureKey={key('find')} summary="Find">
        <p>Target</p>
      </Disclosure>,
    );
    const panel = view.getByText('Target').closest('[data-slot=accordion-content]') as HTMLElement;
    fireEvent(panel, new Event('beforematch'));
    expect(kit.controls.disclosures.isOpen(key('find'))).toBe(true);
    rerender(
      <Disclosure disclosureKey={key('find')} summary="Find">
        <p>Target</p>
      </Disclosure>,
    );
    expect(view.getByRole('button', { name: 'Find' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('publishes only changed snapshots and releases subscriptions on unmount', async () => {
    const { view, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        Body
      </Disclosure>,
    );
    const store = kit.controls.disclosures;
    const snapshots: boolean[] = [];
    const release = store.subscribe(() => snapshots.push(store.isOpen(key('plan'))));
    const closed = store.read(key('plan'));
    act(() => store.set(key('plan'), false));
    expect(store.read(key('plan'))).toBe(closed);
    act(() => store.set(key('plan'), true));
    const opened = store.read(key('plan'));
    act(() => store.set(key('plan'), true));
    expect(store.read(key('plan'))).toBe(opened);
    expect(store.size()).toBe(1);
    act(() => store.set(key('plan'), false));
    expect(store.read(key('plan')).version).toBeGreaterThan(opened.version);
    expect(store.size()).toBe(0);
    expect(snapshots).toEqual([true, false]);
    release();
    view.unmount();
    store.set(key('plan'), true);
    await flushToggle();
    expect(snapshots).toEqual([true, false]);
  });

  it('draws a named controlled button and keeps closed content available to browser find', () => {
    const { view } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        <p>Body</p>
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest<HTMLElement>('[data-slot=accordion],details');
    expect(details).not.toBeNull();
    expect(
      view.getByText('Body').closest('[data-slot=accordion-content]')?.getAttribute('hidden'),
    ).toBe('until-found');
    expect(isOpen(details)).toBe(false);
    expect(view.getByRole('button', { name: 'Project plan' }).getAttribute('aria-expanded')).toBe(
      'false',
    );
  });

  it('comes back open in the markup after a remount, so no opening motion replays', async () => {
    const { view, rerender, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        <p>Body</p>
      </Disclosure>,
    );
    const first = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(first, true);
    await flushToggle();
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(true);

    rerender(<p>elsewhere</p>);
    expect(view.queryByText('Project plan')).toBeNull();

    const records: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => records.push(...batch));
    observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['open'] });
    rerender(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        <p>Body</p>
      </Disclosure>,
    );
    await flushToggle();
    observer.disconnect();
    const second = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    expect(second).not.toBe(first);
    expect(isOpen(second)).toBe(true);
    expect(records).toEqual([]);
  });

  it('is left alone, same node and same state, by an unrelated update', async () => {
    function Page() {
      const [tick, setTick] = useState(0);
      return (
        <div data-tick={tick}>
          <button type="button" onClick={() => setTick(tick + 1)}>
            tick
          </button>
          <Disclosure disclosureKey={key('plan')} summary="Project plan">
            <p>{`Body ${String(tick)}`}</p>
          </Disclosure>
        </div>
      );
    }
    const { view } = mount(<Page />);
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(details, true);
    await flushToggle();
    const records: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => records.push(...batch));
    observer.observe(details, { attributes: true });
    act(() => view.getByRole('button', { name: 'tick' }).click());
    act(() => view.getByRole('button', { name: 'tick' }).click());
    await flushToggle();
    observer.disconnect();
    expect(view.getByText('Project plan').closest('[data-slot=accordion],details')).toBe(details);
    expect(isOpen(details)).toBe(true);
    expect(records).toEqual([]);
    expect(view.getByText('Body 2')).toBeVisible();
  });

  it('keeps one disclosure per key independent of the others', async () => {
    const { view } = mount(
      <>
        <Disclosure disclosureKey={key('plan', 'alpha', 'claude:s1')} summary="Plan A1">
          <p>a1</p>
        </Disclosure>
        <Disclosure disclosureKey={key('plan', 'alpha', 'claude:s2')} summary="Plan A2">
          <p>a2</p>
        </Disclosure>
        <Disclosure disclosureKey={key('plan', 'beta', 'claude:s1')} summary="Plan B1">
          <p>b1</p>
        </Disclosure>
      </>,
    );
    toggle(
      view.getByText('Plan A1').closest('[data-slot=accordion],details') as HTMLDetailsElement,
      true,
    );
    await flushToggle();
    expect(
      isOpen(
        view.getByText('Plan A2').closest('[data-slot=accordion],details') as HTMLDetailsElement,
      ),
    ).toBe(false);
    expect(
      isOpen(
        view.getByText('Plan B1').closest('[data-slot=accordion],details') as HTMLDetailsElement,
      ),
    ).toBe(false);
  });

  it('records a reader toggle for the motion hold, and nothing else does', () => {
    const noteToggle = vi.fn();
    const { view, rerender } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        <p>Body</p>
      </Disclosure>,
      { noteToggle },
    );
    expect(noteToggle).not.toHaveBeenCalled();
    rerender(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        <p>Changed body</p>
      </Disclosure>,
    );
    expect(noteToggle).not.toHaveBeenCalled();
    fireEvent.click(view.getByText('Project plan'));
    expect(noteToggle).toHaveBeenCalledOnce();
  });

  it('forgets an open state when the reader closes it', async () => {
    const { view, kit } = mount(
      <Disclosure disclosureKey={key('plan')} summary="Project plan">
        <p>Body</p>
      </Disclosure>,
    );
    const details = view
      .getByText('Project plan')
      .closest('[data-slot=accordion],details') as HTMLDetailsElement;
    toggle(details, true);
    await flushToggle();
    toggle(details, false);
    await flushToggle();
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(false);
  });
});

describe('controlled popovers keep the dismissal contract', () => {
  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', (run: () => void) => setTimeout(run, 0));
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(() => vi.unstubAllGlobals());
  const settle = async () => {
    for (let i = 0; i < 5; i += 1) await flushToggle();
  };
  function page() {
    return (
      <main id="app">
        <Disclosure disclosureKey={key('why')} summary="Why" variant="popover">
          <button type="button">Inside why</button>
        </Disclosure>
        <Disclosure disclosureKey={key('other')} summary="Other" variant="popover">
          <button type="button">Inside other</button>
        </Disclosure>
        <Disclosure disclosureKey={key('plan')} summary="Plan">
          <p>Plan body</p>
        </Disclosure>
        <button type="button">Elsewhere</button>
      </main>
    );
  }
  const opened = (view: ReturnType<typeof mount>['view'], name = 'Why') =>
    view.getByRole('button', { name }).getAttribute('aria-expanded') === 'true';
  async function openBoth(
    view: ReturnType<typeof mount>['view'],
    kit: ReturnType<typeof mount>['kit'],
  ) {
    act(() => {
      kit.controls.disclosures.set(key('why'), true);
      kit.controls.disclosures.set(key('other'), true);
      kit.controls.disclosures.set(key('plan'), true);
    });
    await settle();
    return view.getByRole('button', { name: 'Why' });
  }
  it('closes every popover on Escape and focuses the document-order fallback while the accordion stays open', async () => {
    const { view, kit } = mount(page());
    const why = await openBoth(view, kit);
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    act(() => view.getByText('Elsewhere').dispatchEvent(event));
    await settle();
    expect(opened(view)).toBe(false);
    expect(opened(view, 'Other')).toBe(false);
    expect(kit.controls.disclosures.isOpen(key('plan'))).toBe(true);
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(why);
  });
  it('returns focus to the owner of a portalled event target', async () => {
    const { view, kit } = mount(page());
    await openBoth(view, kit);
    fireEvent.keyDown(view.getByText('Inside other'), { key: 'Escape' });
    await settle();
    expect(opened(view)).toBe(false);
    expect(opened(view, 'Other')).toBe(false);
    expect(document.activeElement).toBe(view.getByRole('button', { name: 'Other' }));
  });
  function nestedPage() {
    return (
      <main id="app">
        <Disclosure disclosureKey={key('outer')} summary="Outer" variant="popover">
          <Disclosure disclosureKey={key('inner')} summary="Inner" variant="popover">
            <button type="button">Inside inner</button>
          </Disclosure>
        </Disclosure>
        <button type="button">Elsewhere</button>
      </main>
    );
  }
  async function openNested() {
    const mounted = mount(nestedPage());
    act(() => mounted.kit.controls.disclosures.set(key('outer'), true));
    await settle();
    act(() => mounted.kit.controls.disclosures.set(key('inner'), true));
    await settle();
    return mounted;
  }
  it('keeps the popup open through the Base UI forward Tab guard', async () => {
    const { view, kit } = mount(page());
    const why = view.getByRole('button', { name: 'Why' });
    act(() => why.focus());
    fireEvent.click(why);
    await settle();
    const guard = why.nextElementSibling as HTMLElement;
    expect(guard.hasAttribute('data-base-ui-focus-guard')).toBe(true);
    act(() => guard.focus());
    await settle();
    expect(kit.controls.disclosures.isOpen(key('why'))).toBe(true);
    expect(view.getByRole('dialog', { name: 'Why' }).contains(document.activeElement)).toBe(true);
  });
  it('keeps both popovers open when focus enters a nested portal', async () => {
    const { view, kit } = await openNested();
    const outer = view.getByRole('dialog', { name: 'Outer' });
    const inner = view.getByRole('dialog', { name: 'Inner' });
    expect(outer.contains(inner)).toBe(false);
    act(() => view.getByRole('button', { name: 'Inner' }).focus());
    act(() => view.getByText('Inside inner').focus());
    await settle();
    expect(kit.controls.disclosures.isOpen(key('outer'))).toBe(true);
    expect(kit.controls.disclosures.isOpen(key('inner'))).toBe(true);
    expect(view.getByRole('dialog', { name: 'Inner' }).contains(document.activeElement)).toBe(true);
    act(() => view.getByText('Elsewhere').focus());
    await settle();
    expect(kit.controls.disclosures.isOpen(key('outer'))).toBe(false);
    expect(kit.controls.disclosures.isOpen(key('inner'))).toBe(false);
    expect(document.activeElement).toBe(view.getByText('Elsewhere'));
  });
  it('returns Escape from a nested portal to the visible outer trigger', async () => {
    const { view, kit } = await openNested();
    fireEvent.keyDown(view.getByText('Inside inner'), { key: 'Escape' });
    await settle();
    expect(kit.controls.disclosures.isOpen(key('outer'))).toBe(false);
    expect(kit.controls.disclosures.isOpen(key('inner'))).toBe(false);
    expect(document.activeElement).toBe(view.getByRole('button', { name: 'Outer' }));
  });
  it('publishes dismissal before a poll can reopen it', async () => {
    const { view, kit, rerender } = mount(page());
    await openBoth(view, kit);
    fireEvent.keyDown(view.getByText('Elsewhere'), { key: 'Escape' });
    expect(kit.controls.disclosures.isOpen(key('why'))).toBe(false);
    rerender(page());
    await settle();
    expect(opened(view)).toBe(false);
  });
  it('does not swallow Escape when no popover is open', () => {
    const { view } = mount(page());
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    act(() => view.getByText('Elsewhere').dispatchEvent(event));
    expect(event.defaultPrevented).toBe(false);
  });
  it('keeps trigger focus on opening and mounts the popup inside the app root', async () => {
    const { view } = mount(page());
    const why = view.getByRole('button', { name: 'Why' });
    why.focus();
    fireEvent.click(why);
    await settle();
    expect(document.activeElement).toBe(why);
    expect(view.getByRole('dialog').closest('#app')).not.toBeNull();
    expect(view.getByRole('dialog').querySelector('[data-slot=popover-close]')).toBeNull();
  });
  it('dismisses outside without stealing the destination focus or its click', async () => {
    const { view, kit } = mount(page());
    fireEvent.click(view.getByRole('button', { name: 'Why' }));
    await settle();
    const outside = view.getByText('Elsewhere');
    const clicked = vi.fn();
    outside.addEventListener('click', clicked);
    act(() => outside.focus());
    fireEvent.pointerDown(outside);
    fireEvent.mouseDown(outside);
    fireEvent.pointerUp(outside);
    fireEvent.click(outside);
    await settle();
    expect(kit.controls.disclosures.isOpen(key('why'))).toBe(false);
    expect(document.activeElement).toBe(outside);
    expect(clicked).toHaveBeenCalledOnce();
  });
  it('keeps an inside click open and ignores a focus departure with no related target', async () => {
    const { view } = mount(page());
    const why = view.getByRole('button', { name: 'Why' });
    why.focus();
    fireEvent.click(why);
    await settle();
    fireEvent.click(view.getByText('Inside why'));
    fireEvent.focusOut(why, { relatedTarget: null });
    await settle();
    expect(opened(view)).toBe(true);
    act(() => view.getByText('Elsewhere').focus());
    await settle();
    expect(opened(view)).toBe(false);
    expect(document.activeElement).toBe(view.getByText('Elsewhere'));
  });
  it('scrolls once on an opening press and keeps popup identity and focus across a poll', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const { view, rerender } = mount(page());
    const why = view.getByRole('button', { name: 'Why' });
    why.focus();
    fireEvent.click(why);
    await settle();
    const popup = view.getByRole('dialog');
    expect(scroll).toHaveBeenCalledOnce();
    rerender(page());
    await settle();
    expect(view.getByRole('dialog')).toBe(popup);
    expect(document.activeElement).toBe(why);
    expect(scroll).toHaveBeenCalledOnce();
  });
  it('follows external writes and restores the open snapshot on a remount without scrolling', async () => {
    const { view, kit, rerender } = mount(page());
    act(() => kit.controls.disclosures.set(key('why'), true));
    await settle();
    expect(opened(view)).toBe(true);
    rerender(<p>elsewhere</p>);
    rerender(page());
    await settle();
    expect(opened(view)).toBe(true);
    expect(view.getByRole('dialog', { name: 'Why' })).toBeVisible();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    act(() => kit.controls.disclosures.set(key('why'), false));
    await settle();
    expect(opened(view)).toBe(false);
  });
  it('releases the document Escape handler after StrictMode cleanup', () => {
    const add = vi.spyOn(document, 'addEventListener');
    const remove = vi.spyOn(document, 'removeEventListener');
    const { view } = mount(page());
    view.unmount();
    const ours = (calls: typeof add.mock.calls) =>
      calls.filter(([name, , capture]) => name === 'keydown' && capture === true).length;
    expect(ours(add.mock.calls)).toBeGreaterThan(0);
    expect(ours(remove.mock.calls)).toBe(ours(add.mock.calls));
    add.mockRestore();
    remove.mockRestore();
  });
});

describe('an accordion that opens by default', () => {
  const accordion = (view: ReturnType<typeof mount>['view']) =>
    view.getByText('Phase').closest('[data-slot=accordion]') as HTMLElement;

  it('opens the first time its key is drawn and keeps a reader’s close through a redraw', () => {
    const ui = (
      <Disclosure disclosureKey={key('phase')} summary="Phase" openByDefault>
        Lines
      </Disclosure>
    );
    const { view, rerender, kit } = mount(ui);
    expect(isOpen(accordion(view))).toBe(true);
    toggle(accordion(view), false);
    expect(isOpen(accordion(view))).toBe(false);
    rerender(ui);
    expect(isOpen(accordion(view))).toBe(false);
    expect(kit.controls.disclosures.isOpen(key('phase'))).toBe(false);
  });

  it('does not reopen a key the reader has closed before it is drawn again', () => {
    const kit = testControls();
    kit.controls.disclosures.set(key('phase'), false);
    const view = render(
      <ControlsProvider controls={kit.controls}>
        <Disclosure disclosureKey={key('phase')} summary="Phase" openByDefault>
          Lines
        </Disclosure>
      </ControlsProvider>,
    );
    expect(isOpen(accordion(view as never))).toBe(false);
  });

  it('stays closed without the prop', () => {
    const { view } = mount(
      <Disclosure disclosureKey={key('phase')} summary="Phase">
        Lines
      </Disclosure>,
    );
    expect(isOpen(accordion(view))).toBe(false);
  });
});
