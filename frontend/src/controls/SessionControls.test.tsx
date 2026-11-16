import { act, fireEvent, render } from '@testing-library/react';
import { StrictMode, useState, type ReactElement } from 'react';
import { describe, expect, it } from 'vitest';
import type { FocusOutcome, SessionIdentity } from '../api/types';
import { ControlsProvider } from './ControlsProvider';
import { CopyControl } from './CopyControl';
import { CUE_TTL_MS, laneKey } from './keyedState';
import { RaiseControl } from './RaiseControl';
import { resumeCommand } from './resumeCommand';
import { testControls, type TestControlsOptions } from './testControls';

function mount(ui: ReactElement, options: TestControlsOptions = {}, strict = true) {
  const kit = testControls(options);
  const wrap = (node: ReactElement) => {
    const inner = <ControlsProvider controls={kit.controls}>{node}</ControlsProvider>;
    return strict ? <StrictMode>{inner}</StrictMode> : inner;
  };
  const view = render(wrap(ui));
  return { kit, view, rerender: (node: ReactElement) => view.rerender(wrap(node)) };
}

const flush = async () => {
  for (let turn = 0; turn < 8; turn += 1) await act(() => Promise.resolve());
};

const ID = { harness: 'claude', sid: 's-1' };

function controls(extra: ReactElement | null = null) {
  return (
    <div>
      <CopyControl kind="id" {...ID} value="s-1" />
      <CopyControl
        kind="link"
        {...ID}
        value="http://127.0.0.1:4580/?all=1#n=session:p:claude:s-1"
      />
      <CopyControl kind="command" {...ID} value="claude --resume s-1" />
      {extra}
    </div>
  );
}

describe('copy controls: ID, absolute link and resume command', () => {
  it('names each control for what it copies and carries the payload as the no-clipboard fallback title', () => {
    const { view } = mount(controls());
    expect(view.getByRole('button', { name: 'Copy session ID s-1' }).getAttribute('title')).toBe(
      's-1',
    );
    expect(
      view.getByRole('button', { name: 'Copy a link to this session' }).getAttribute('title'),
    ).toContain('#n=session:p:claude:s-1');
    expect(
      view
        .getByRole('button', { name: 'Copy re-entry command claude --resume s-1' })
        .getAttribute('title'),
    ).toBe('claude --resume s-1');
  });

  it('writes nothing to the clipboard and announces nothing on mount, re-render or StrictMode double effects', async () => {
    const { kit, rerender } = mount(controls());
    rerender(controls());
    rerender(controls());
    await flush();
    expect(kit.written).toEqual([]);
    expect(kit.announced).toEqual([]);
  });

  it("copies exactly the control's own value once per press and announces it once, under a key for that press", async () => {
    const { kit, view } = mount(controls());
    fireEvent.click(view.getByRole('button', { name: 'Copy session ID s-1' }));
    await flush();
    expect(kit.written).toEqual(['s-1']);
    expect(kit.announced).toHaveLength(1);
    expect(kit.announced[0]?.text).toBe('Copied session ID s-1');
    fireEvent.click(view.getByRole('button', { name: 'Copy session ID s-1' }));
    await flush();
    expect(kit.written).toEqual(['s-1', 's-1']);
    expect(kit.announced).toHaveLength(2);
    expect(kit.announced[1]?.key).not.toBe(kit.announced[0]?.key);
  });

  it('gives each of the three controls its own cue, so copying the ID does not mark the command copied', async () => {
    const { kit, view } = mount(controls());
    fireEvent.click(view.getByRole('button', { name: 'Copy session ID s-1' }));
    await flush();
    expect(
      view.getByRole('button', { name: 'Copy session ID s-1' }).getAttribute('data-copy-state'),
    ).toBe('copied');
    expect(
      view
        .getByRole('button', { name: 'Copy a link to this session' })
        .hasAttribute('data-copy-state'),
    ).toBe(false);
    expect(
      view.getByRole('button', { name: /Copy re-entry command/ }).hasAttribute('data-copy-state'),
    ).toBe(false);
    expect(kit.controls.cues.read(laneKey('copy', 'claude', 's-1'))).toBe('copied');
    expect(kit.controls.cues.read(laneKey('link', 'claude', 's-1'))).toBeUndefined();
    expect(kit.controls.cues.read(laneKey('command', 'claude', 's-1'))).toBeUndefined();
  });

  it('keeps the link and the command in lanes of their own, each marked only by its own press', async () => {
    const { kit, view } = mount(controls());
    fireEvent.click(view.getByRole('button', { name: 'Copy a link to this session' }));
    await flush();
    expect(
      view
        .getByRole('button', { name: 'Copy a link to this session' })
        .getAttribute('data-copy-state'),
    ).toBe('copied');
    expect(
      view.getByRole('button', { name: /Copy re-entry command/ }).hasAttribute('data-copy-state'),
    ).toBe(false);
    expect(kit.controls.cues.read(laneKey('link', 'claude', 's-1'))).toBe('copied');
    expect(kit.controls.cues.read(laneKey('command', 'claude', 's-1'))).toBeUndefined();
    fireEvent.click(view.getByRole('button', { name: /Copy re-entry command/ }));
    await flush();
    expect(kit.controls.cues.read(laneKey('command', 'claude', 's-1'))).toBe('copied');
    expect(kit.controls.cues.read(laneKey('copy', 'claude', 's-1'))).toBeUndefined();
    expect(kit.announced.map((entry) => entry.text)).toEqual([
      'Copied a link to this session',
      'Copied claude --resume s-1',
    ]);
  });

  it('keeps the cue on a node that is replaced, then lets it lapse after thirty seconds', async () => {
    function Page() {
      const [generation, setGeneration] = useState(0);
      return (
        <div key={generation}>
          <button type="button" onClick={() => setGeneration(generation + 1)}>
            redraw
          </button>
          <CopyControl kind="command" {...ID} value="claude --resume s-1" />
        </div>
      );
    }
    const { kit, view } = mount(<Page />);
    const name = 'Copy re-entry command claude --resume s-1';
    fireEvent.click(view.getByRole('button', { name }));
    await flush();
    const before = view.getByRole('button', { name });
    act(() => view.getByRole('button', { name: 'redraw' }).click());
    const after = view.getByRole('button', { name });
    expect(after).not.toBe(before);
    expect(after.getAttribute('data-copy-state')).toBe('copied');
    act(() => kit.clock.advance(CUE_TTL_MS));
    expect(view.getByRole('button', { name }).hasAttribute('data-copy-state')).toBe(false);
  });

  it('shows the cue to a keyboard or screen-reader user as text, not colour alone', async () => {
    const { view } = mount(controls());
    const button = view.getByRole('button', { name: 'Copy session ID s-1' });
    expect(button.hasAttribute('aria-describedby')).toBe(false);
    fireEvent.click(button);
    await flush();
    const described = button.getAttribute('aria-describedby');
    expect(described).not.toBeNull();
    expect(document.getElementById(described ?? '')?.textContent).toBe('Copied');
  });

  it('reports a rejected clipboard as a failure, distinct from success, and sets the failed cue', async () => {
    const { kit, view } = mount(controls(), { clipboard: 'rejects' });
    fireEvent.click(view.getByRole('button', { name: 'Copy a link to this session' }));
    await flush();
    expect(kit.announced.map((entry) => entry.text)).toEqual([
      'The link to this session could not be copied',
    ]);
    expect(
      view
        .getByRole('button', { name: 'Copy a link to this session' })
        .getAttribute('data-copy-state'),
    ).toBe('failed');
  });

  it('reports a context with no clipboard as a failure rather than pretending', async () => {
    const { kit, view } = mount(controls(), { clipboard: 'missing' });
    fireEvent.click(
      view.getByRole('button', { name: 'Copy re-entry command claude --resume s-1' }),
    );
    await flush();
    expect(kit.announced.map((entry) => entry.text)).toEqual([
      'Re-entry command could not be copied',
    ]);
    expect(kit.written).toEqual([]);
  });

  it('copies nothing for an empty value', async () => {
    const { kit, view } = mount(<CopyControl kind="id" harness="claude" sid="s-1" value="" />);
    fireEvent.click(view.getByRole('button'));
    await flush();
    expect(kit.written).toEqual([]);
    expect(kit.announced.map((entry) => entry.text)).toEqual(['Session ID could not be copied']);
  });

  it('keeps cues for the same sid under two harnesses apart', async () => {
    const { view } = mount(
      <>
        <CopyControl kind="id" harness="claude" sid="same" value="same" />
        <CopyControl kind="id" harness="codex" sid="same" value="same" />
      </>,
    );
    const [first, second] = view.getAllByRole('button');
    fireEvent.click(first as HTMLElement);
    await flush();
    expect(first?.getAttribute('data-copy-state')).toBe('copied');
    expect(second?.hasAttribute('data-copy-state')).toBe(false);
  });
});

describe('the resume command is built only for a known harness and a safe token', () => {
  it('builds the released verbs and refuses everything else', () => {
    expect(resumeCommand('claude', 'abc-1')).toBe('claude --resume abc-1');
    expect(resumeCommand('codex', 'abc_1')).toBe('codex resume abc_1');
    expect(resumeCommand('gemini', 'abc')).toBe('');
    expect(resumeCommand('claude', '-x')).toBe('');
    expect(resumeCommand('claude', 'a b')).toBe('');
    expect(resumeCommand('claude', 'a;rm')).toBe('');
    expect(resumeCommand('claude', 'x'.repeat(65))).toBe('');
    expect(resumeCommand('claude', 'x'.repeat(64))).toBe(`claude --resume ${'x'.repeat(64)}`);
    expect(resumeCommand('claude', '')).toBe('');
  });
});

function raiseHarness(outcome: FocusOutcome | (() => Promise<FocusOutcome>)) {
  const calls: SessionIdentity[] = [];
  const focus = (identity: SessionIdentity): Promise<FocusOutcome> => {
    calls.push(identity);
    if (typeof outcome === 'function') return outcome();
    return Promise.resolve(outcome);
  };
  return { calls, focus };
}

describe('terminal raise', () => {
  const ui = (
    <>
      <RaiseControl harness="claude" sid="s-1" focusable />
      <RaiseControl harness="codex" sid="s-1" focusable />
    </>
  );

  it('draws nothing when the feature is off for the run, and nothing for a row that is not focusable', () => {
    const off = mount(ui, { focus: null });
    expect(off.view.queryByRole('button')).toBeNull();
    off.view.unmount();
    const notFocusable = mount(<RaiseControl harness="claude" sid="s-1" focusable={false} />);
    expect(notFocusable.view.queryByRole('button')).toBeNull();
  });

  it('sends nothing on mount, StrictMode or a re-render: a raise needs a press', async () => {
    const harness = raiseHarness('sent');
    const { rerender, kit } = mount(ui, { focus: harness.focus });
    rerender(ui);
    await flush();
    expect(harness.calls).toEqual([]);
    expect(kit.announced).toEqual([]);
  });

  it('is named for the act, not the target, and reports an unraised terminal honestly', async () => {
    const harness = raiseHarness('sent');
    const { view, kit } = mount(ui, { focus: harness.focus });
    const [first] = view.getAllByRole('button', {
      name: 'Raise the terminal this session is running in',
    });
    fireEvent.click(first as HTMLElement);
    await flush();
    expect(harness.calls).toEqual([{ harness: 'claude', sid: 's-1' }]);
    expect(kit.announced.map((entry) => entry.text)).toEqual([
      'Raise requested',
      'Raise sent; the terminal switched to this session. Its window may still be behind others.',
    ]);
    expect(first?.getAttribute('data-raise-state')).toBe('sent');
  });

  it.each([
    ['declined', 'No terminal was raised'],
    ['throttled', 'Raise refused: another raise was too recent. Try again in a moment.'],
    ['stale', 'Raise refused: the dashboard restarted. Reload the page.'],
    ['failed', 'Raise could not be sent'],
  ] as const)('maps the %s outcome to its own sentence and cue', async (outcome, sentence) => {
    const harness = raiseHarness(outcome);
    const { view, kit } = mount(<RaiseControl harness="claude" sid="s-1" focusable />, {
      focus: harness.focus,
    });
    fireEvent.click(view.getByRole('button'));
    await flush();
    expect(kit.announced.at(-1)?.text).toBe(sentence);
    expect(view.getByRole('button').getAttribute('data-raise-state')).toBe(outcome);
  });

  it('keeps the server refusal beside the pressed row across a remount', async () => {
    const message =
      'Compass refused this request: board actions require direct loopback access from the same origin.';
    const { view, kit, rerender } = mount(<RaiseControl harness="claude" sid="s-1" focusable />, {
      focus: async () => ({ state: 'refused', message }),
    });
    fireEvent.click(view.getByRole('button'));
    await flush();
    expect(kit.announced.at(-1)?.text).toBe(message);
    rerender(<div />);
    rerender(<RaiseControl harness="claude" sid="s-1" focusable />);
    expect(view.getByRole('button').getAttribute('data-raise-state')).toBe('refused');
    expect(view.getByText(message).textContent).not.toContain('restarted');
    expect(view.getByRole('button').getAttribute('aria-describedby')).toBe(
      view.getByText(message).id,
    );
    act(() => kit.clock.advance(CUE_TTL_MS));
    expect(view.queryByText(message)).toBeNull();
    expect(view.getByRole('button').hasAttribute('aria-describedby')).toBe(false);
  });

  it('says nothing and leaves no cue when the runtime reports the feature unavailable', async () => {
    const harness = raiseHarness('unavailable');
    const { view, kit } = mount(<RaiseControl harness="claude" sid="s-1" focusable />, {
      focus: harness.focus,
    });
    fireEvent.click(view.getByRole('button'));
    await flush();
    expect(view.getByRole('button').hasAttribute('data-raise-state')).toBe(false);
    expect(kit.announced.at(-1)?.text).toBe('Raise requested');
  });

  it('deduplicates while one is in flight: every RAISE reads busy, the second press sends nothing and is told why', async () => {
    let settle: (value: FocusOutcome) => void = () => undefined;
    const harness = raiseHarness(
      () =>
        new Promise<FocusOutcome>((resolve) => {
          settle = resolve;
        }),
    );
    const { view, kit } = mount(ui, { focus: harness.focus });
    const [first, second] = view.getAllByRole('button');
    fireEvent.click(first as HTMLElement);
    await flush();
    expect(first?.getAttribute('aria-disabled')).toBe('true');
    expect(second?.getAttribute('aria-disabled')).toBe('true');
    // aria-disabled, never disabled: the control keeps its place in the tab order and its focus.
    expect((second as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(second as HTMLElement);
    await flush();
    expect(harness.calls).toHaveLength(1);
    expect(second?.getAttribute('data-raise-state')).toBe('throttled');
    expect(kit.announced.at(-1)?.text).toBe(
      'Raise refused: another raise was too recent. Try again in a moment.',
    );
    await act(async () => {
      settle('sent');
      await Promise.resolve();
    });
    await flush();
    expect(first?.hasAttribute('aria-disabled')).toBe(false);
    expect(second?.hasAttribute('aria-disabled')).toBe(false);
  });

  it('does not steal focus while busy', async () => {
    let settle: (value: FocusOutcome) => void = () => undefined;
    const harness = raiseHarness(
      () =>
        new Promise<FocusOutcome>((resolve) => {
          settle = resolve;
        }),
    );
    const { view } = mount(<RaiseControl harness="claude" sid="s-1" focusable />, {
      focus: harness.focus,
    });
    const button = view.getByRole('button');
    button.focus();
    fireEvent.click(button);
    await flush();
    expect(document.activeElement).toBe(button);
    await act(async () => {
      settle('declined');
      await Promise.resolve();
    });
    expect(document.activeElement).toBe(button);
  });

  it('refuses an identity with an empty harness or sid before any request', async () => {
    const harness = raiseHarness('sent');
    const { view } = mount(<RaiseControl harness="" sid="s-1" focusable />, {
      focus: harness.focus,
    });
    expect(view.queryByRole('button')).toBeNull();
    expect(harness.calls).toEqual([]);
  });

  it('keeps its cue across a replaced node and lets it lapse', async () => {
    const harness = raiseHarness('sent');
    function Page() {
      const [generation, setGeneration] = useState(0);
      return (
        <div key={generation}>
          <button type="button" onClick={() => setGeneration(generation + 1)}>
            redraw
          </button>
          <RaiseControl harness="claude" sid="s-1" focusable />
        </div>
      );
    }
    const { view, kit } = mount(<Page />, { focus: harness.focus });
    fireEvent.click(view.getByRole('button', { name: /Raise the terminal/ }));
    await flush();
    act(() => view.getByRole('button', { name: 'redraw' }).click());
    expect(
      view.getByRole('button', { name: /Raise the terminal/ }).getAttribute('data-raise-state'),
    ).toBe('sent');
    act(() => kit.clock.advance(CUE_TTL_MS));
    expect(
      view.getByRole('button', { name: /Raise the terminal/ }).hasAttribute('data-raise-state'),
    ).toBe(false);
  });

  it('draws the primary variant for a session waiting on the reader', () => {
    const { view } = mount(<RaiseControl harness="claude" sid="s-1" focusable primary />);
    expect(view.getByRole('button').getAttribute('data-variant')).toBe('raise-primary');
  });
});
