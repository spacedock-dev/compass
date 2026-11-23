import { act, fireEvent, render } from '@testing-library/react';
import { StrictMode, useState, type ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { contextKey } from '../api/identity';
import { memoKey } from '../storage';
import { ControlsProvider } from './ControlsProvider';
import { BriefingUnavailable } from './briefingUnavailable';
import { MoreMenu, type MoreMenuProps } from './MoreMenu';
import { testControls, type TestControlsOptions } from './testControls';

const FOCUS = { harness: 'claude', sid: 's-1' };

function menu(props: Partial<MoreMenuProps> = {}): ReactElement {
  return (
    <MoreMenu projectKey="alpha/app" focus={null} briefingText={() => 'BRIEFING TEXT'} {...props} />
  );
}

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

const flush = async () => {
  for (let turn = 0; turn < 8; turn += 1) await act(() => Promise.resolve());
};

describe('the project More menu', () => {
  it('names its summary and offers Copy briefing without a duplicate fleet count', () => {
    const { view } = mount(menu());
    const summary = view.getByText('More').closest('summary');
    expect(summary?.getAttribute('aria-label')).toBe('More');
    expect(summary?.querySelector('svg[data-icon="caret-down"]')).toBeInTheDocument();
    expect(view.queryByText(/All projects.*subagents? observed/)).toBeNull();
    expect(view.getByRole('button', { name: 'Copy briefing' })).toBeInTheDocument();
    expect(view.queryByRole('button', { name: 'Add human context' })).toBeNull();
  });

  it('offers Add human context only when the caller says the note is empty and the briefing complete', () => {
    const key = memoKey('alpha/app', null, 'outcome');
    const { view, kit } = mount(menu({ addHumanContext: { memoKey: key } }));
    fireEvent.click(view.getByRole('button', { name: 'Add human context' }));
    expect(kit.controls.memoEditing.get()?.key).toBe(key);
  });

  it('does not read the briefing, touch the clipboard or announce on mount, re-render or StrictMode', async () => {
    const briefingText = vi.fn(() => 'BRIEFING TEXT');
    const { kit, rerender } = mount(menu({ briefingText }));
    rerender(menu({ briefingText }));
    await flush();
    expect(briefingText).not.toHaveBeenCalled();
    expect(kit.written).toEqual([]);
    expect(kit.announced).toEqual([]);
  });

  it('copies the briefing once per press and reads Copied until the scope changes, with no expiry', async () => {
    const { view, kit, rerender } = mount(menu());
    fireEvent.click(view.getByRole('button', { name: 'Copy briefing' }));
    await flush();
    expect(kit.written).toEqual(['BRIEFING TEXT']);
    expect(view.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(kit.announced).toHaveLength(1);
    act(() => kit.clock.advance(24 * 60 * 60 * 1000));
    expect(view.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
    // Another session's context key is another state; the project's own comes back with it.
    rerender(menu({ focus: FOCUS }));
    expect(view.getByRole('button', { name: 'Copy briefing' })).toBeInTheDocument();
    rerender(menu({ focus: null }));
    expect(view.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(kit.controls.briefing.read(contextKey('alpha/app', null))).toBe('copied');
  });

  it('says why the briefing cannot be built, rather than blaming the clipboard', async () => {
    const unbuilt = mount(
      menu({
        briefingText: () => {
          throw new BriefingUnavailable('The project is not in the current payload.');
        },
      }),
    );
    fireEvent.click(unbuilt.view.getByRole('button', { name: 'Copy briefing' }));
    await flush();
    expect(unbuilt.view.getByRole('button', { name: 'Copy unavailable' })).toBeInTheDocument();
    expect(unbuilt.kit.announced.map((entry) => entry.text)).toEqual([
      'The project is not in the current payload.',
    ]);
  });

  it('reads Copy unavailable for a rejected clipboard and for none at all', async () => {
    const rejected = mount(menu(), { clipboard: 'rejects' });
    fireEvent.click(rejected.view.getByRole('button', { name: 'Copy briefing' }));
    await flush();
    expect(rejected.view.getByRole('button', { name: 'Copy unavailable' })).toBeInTheDocument();
    rejected.view.unmount();
    const none = mount(menu(), { clipboard: 'missing' });
    fireEvent.click(none.view.getByRole('button', { name: 'Copy briefing' }));
    await flush();
    expect(none.view.getByRole('button', { name: 'Copy unavailable' })).toBeInTheDocument();
    expect(none.kit.written).toEqual([]);
  });

  it('keeps its open state and summary focus through unrelated updates and a remount', async () => {
    function Page() {
      const [tick, setTick] = useState(0);
      return (
        <div>
          <button type="button" onClick={() => setTick(tick + 1)}>
            tick
          </button>
          {menu({ briefingText: () => String(tick) })}
        </div>
      );
    }
    const { view, rerender } = mount(<Page />);
    const details = view.getByText('More').closest('details') as HTMLDetailsElement;
    act(() => {
      details.open = true;
    });
    await act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
    const summary = view.getByText('More');
    summary.focus();
    act(() => view.getByRole('button', { name: 'tick' }).click());
    expect(view.getByText('More').closest('details')).toBe(details);
    expect(details.open).toBe(true);
    expect(document.activeElement).toBe(summary);
    rerender(<p>another view</p>);
    rerender(<Page />);
    expect(
      (view.getByText('More').closest('details') as HTMLDetailsElement).hasAttribute('open'),
    ).toBe(true);
  });

  it('keeps its summary keyboard operable and a menu is not dismissed by Escape as a popover is', async () => {
    const { view } = mount(menu());
    const details = view.getByText('More').closest('details') as HTMLDetailsElement;
    act(() => {
      details.open = true;
    });
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    act(() => {
      view.getByText('More').dispatchEvent(escape);
    });
    expect(details.open).toBe(true);
    expect(escape.defaultPrevented).toBe(false);
  });
});
