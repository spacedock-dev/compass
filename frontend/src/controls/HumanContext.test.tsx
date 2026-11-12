import { act, fireEvent, render } from '@testing-library/react';
import { StrictMode, useState, type ReactElement } from 'react';
import { useValueStore } from './kit';
import { describe, expect, it, vi } from 'vitest';
import { blockedBackend, fakeBackend } from '../../test/storage_backends';
import { createLegacyStorage, memoKey, MEMO_LIMIT } from '../storage';
import { ControlsProvider } from './ControlsProvider';
import { HumanContextField } from './HumanContextField';
import { testControls, type TestControlsOptions } from './testControls';

const KEY = memoKey('alpha/app', null, 'outcome');
const FOCUS_KEY = memoKey('alpha/app', null, 'focus');

function field(kind: 'outcome' | 'focus' = 'outcome'): ReactElement {
  return kind === 'outcome' ? (
    <HumanContextField
      memoKey={KEY}
      kind="outcome"
      label="OUTCOME"
      placeholder="What result should this scope achieve?"
    />
  ) : (
    <HumanContextField
      memoKey={FOCUS_KEY}
      kind="focus"
      label="FOCUS"
      placeholder="What are you concentrating on now?"
    />
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

function type(textarea: HTMLElement, text: string) {
  act(() => {
    (textarea as HTMLTextAreaElement).value = text;
    fireEvent.input(textarea);
  });
}

const settle = () => act(() => Promise.resolve());

function edit(view: ReturnType<typeof mount>['view'], label = 'Edit OUTCOME') {
  fireEvent.click(view.getByRole('button', { name: label }));
  return view.getByRole('textbox') as HTMLTextAreaElement;
}

describe('human context: a note kept in this browser, saved on every input', () => {
  it('reads Not set, names its Edit control, and writes nothing on mount or StrictMode double effects', () => {
    const { view, kit } = mount(field());
    expect(view.getByText('Not set')).toBeVisible();
    expect(view.getByRole('button', { name: 'Edit OUTCOME' })).toBeVisible();
    expect(kit.backend.writes).toEqual([]);
    expect(kit.announced).toEqual([]);
  });

  it('shows what storage already holds, bounded to 2000 code points', () => {
    const backend = fakeBackend({ [KEY]: 'y'.repeat(2100) });
    const { view } = mount(field(), { backend });
    expect(view.getByText('y'.repeat(MEMO_LIMIT))).toBeVisible();
  });

  it('opens an editor that takes focus, accepts a whole paste and says it autosaves', () => {
    const { view } = mount(field());
    const textarea = edit(view);
    expect(document.activeElement).toBe(textarea);
    expect(textarea.hasAttribute('maxlength')).toBe(false);
    expect(textarea.getAttribute('placeholder')).toBe('What result should this scope achieve?');
    expect(view.getByText('Autosaves in this browser')).toBeVisible();
    expect(view.getByRole('button', { name: 'Done' })).toBeVisible();
    expect(textarea.labels?.[0]?.textContent).toContain('OUTCOME');
  });

  it('saves each input to the exact released key, memory first, and says so', () => {
    const { view, kit } = mount(field());
    const textarea = edit(view);
    type(textarea, 'Ship the importer');
    expect(kit.backend.data.get(KEY)).toBe('Ship the importer');
    expect(kit.backend.writes).toEqual([KEY]);
    expect(view.getByText('Saved in this browser')).toBeVisible();
  });

  it('accepts 1050 emoji and counts 1600 emoji as 1600 characters', () => {
    const { view, kit } = mount(field());
    const textarea = edit(view);
    type(textarea, '😀'.repeat(1600));
    expect(view.getByText('1600/2000')).toBeVisible();
    type(textarea, '😀'.repeat(1050));
    expect(textarea.hasAttribute('aria-invalid')).toBe(false);
    expect(view.queryByText(/characters; the limit/)).toBeNull();
    expect(kit.backend.data.get(KEY)).toBe('😀'.repeat(1050));
  });

  it('keeps each unfinished draft and its original across switching editors, until Done or Escape', () => {
    const backend = fakeBackend({ [KEY]: 'original outcome', [FOCUS_KEY]: 'original focus' });
    const fields = (
      <>
        {field('outcome')}
        {field('focus')}
      </>
    );
    const { view, kit, rerender } = mount(fields, { backend });
    type(edit(view), 'autosaved outcome');
    const text = '😀'.repeat(2100);
    type(view.getByRole('textbox'), text);
    const writes = backend.writes.length;
    type(edit(view, 'Edit FOCUS'), 'autosaved focus');
    // This is the same entry point RecoveryStrip and MoreMenu call.
    act(() => kit.controls.startMemoEdit(KEY));
    expect((view.getByRole('textbox') as HTMLTextAreaElement).value).toBe(text);
    expect((view.getByRole('button', { name: 'Done' }) as HTMLButtonElement).disabled).toBe(true);
    expect(backend.data.get(KEY)).toBe('autosaved outcome');
    expect(backend.writes).toHaveLength(writes + 1);
    rerender(<p>elsewhere</p>);
    rerender(fields);
    expect((view.getByRole('textbox') as HTMLTextAreaElement).value).toBe(text);
    fireEvent.keyDown(view.getByRole('textbox'), { key: 'Escape' });
    expect(backend.data.get(KEY)).toBe('original outcome');
    type(edit(view), 'completed outcome');
    fireEvent.click(view.getByRole('button', { name: 'Done' }));
    edit(view);
    fireEvent.keyDown(view.getByRole('textbox'), { key: 'Escape' });
    expect(backend.data.get(KEY)).toBe('completed outcome');
    edit(view, 'Edit FOCUS');
    expect((view.getByRole('textbox') as HTMLTextAreaElement).value).toBe('autosaved focus');
    fireEvent.keyDown(view.getByRole('textbox'), { key: 'Escape' });
    expect(backend.data.get(FOCUS_KEY)).toBe('original focus');
  });

  it('reopens an untouched parked memo with another tab’s saved words', () => {
    const backend = fakeBackend({ [KEY]: 'original outcome' });
    const { view } = mount(
      <>
        {field('outcome')}
        {field('focus')}
      </>,
      { backend },
    );
    edit(view);
    edit(view, 'Edit FOCUS');
    createLegacyStorage(() => backend).memo.write(KEY, 'saved in another tab');
    const writes = backend.writes.length;
    expect(edit(view).value).toBe('saved in another tab');
    fireEvent.keyDown(view.getByRole('textbox'), { key: 'Escape' });
    expect(view.getByText('saved in another tab')).toBeVisible();
    expect(backend.data.get(KEY)).toBe('saved in another tab');
    expect(backend.writes).toHaveLength(writes);
  });

  it.each(['untouched', 'autosaved', 'over limit'] as const)(
    'takes another tab’s save on Escape from an %s memo without writing',
    (draft) => {
      const backend = fakeBackend({ [KEY]: 'original outcome' });
      const { view } = mount(field(), { backend });
      const textarea = edit(view);
      if (draft !== 'untouched') type(textarea, 'my autosaved words');
      if (draft === 'over limit') type(textarea, '😀'.repeat(2100));
      createLegacyStorage(() => backend).memo.write(KEY, 'saved in another tab');
      const writes = backend.writes.length;
      fireEvent.keyDown(textarea, { key: 'Escape' });
      expect(view.getByText('saved in another tab')).toBeVisible();
      expect(backend.data.get(KEY)).toBe('saved in another tab');
      expect(backend.writes).toHaveLength(writes);
      expect(edit(view).value).toBe('saved in another tab');
    },
  );

  it('refreshes a completed memo when reopened after another tab saves', () => {
    const backend = fakeBackend({ [KEY]: 'original outcome' });
    const { view } = mount(field(), { backend });
    type(edit(view), 'completed here');
    fireEvent.click(view.getByRole('button', { name: 'Done' }));
    createLegacyStorage(() => backend).memo.write(KEY, 'saved in another tab');
    expect(edit(view).value).toBe('saved in another tab');
  });

  it('updates the counter without notifying editor subscribers or rendering their readers', () => {
    const kit = testControls();
    let renders = 0;
    function Reader() {
      useValueStore(kit.controls.memoEditing);
      renders += 1;
      return null;
    }
    const view = render(
      <ControlsProvider controls={kit.controls}>
        <Reader />
        {field()}
      </ControlsProvider>,
    );
    const textarea = edit(view);
    const before = renders;
    let notifications = 0;
    const stop = kit.controls.memoEditing.subscribe(() => {
      notifications += 1;
    });
    type(textarea, 'x'.repeat(1600));
    expect(view.getByText('1600/2000')).toBeVisible();
    expect(notifications).toBe(0);
    expect(renders).toBe(before);
    stop();
  });

  it.each(['界'.repeat(2100), '😀'.repeat(2100)])(
    'keeps an over-limit paste without autosaving, and saves after editing back',
    (text) => {
      const backend = fakeBackend({ [KEY]: 'original' });
      const { view, kit, rerender } = mount(field(), { backend });
      const textarea = edit(view);
      type(textarea, text);
      expect((textarea as HTMLInputElement | HTMLTextAreaElement).value).toBe(text);
      expect(textarea.getAttribute('aria-invalid')).toBe('true');
      expect(view.getByText('2100/2000').getAttribute('data-over')).toBe('true');
      expect(view.getByText('2100 characters; the limit is 2000.')).toBeVisible();
      expect((view.getByRole('button', { name: 'Done' }) as HTMLButtonElement).disabled).toBe(true);
      expect(kit.backend.data.get(KEY)).toBe('original');
      expect(kit.backend.writes).toEqual([]);
      expect(view.queryByText('Saved in this browser')).toBeNull();
      rerender(<p>elsewhere</p>);
      rerender(field());
      expect((view.getByRole('textbox') as HTMLInputElement | HTMLTextAreaElement).value).toBe(
        text,
      );
      expect((view.getByRole('button', { name: 'Done' }) as HTMLButtonElement).disabled).toBe(true);
      type(view.getByRole('textbox'), Array.from(text).slice(0, 2000).join(''));
      expect((view.getByRole('button', { name: 'Done' }) as HTMLButtonElement).disabled).toBe(
        false,
      );
      expect(kit.backend.data.get(KEY)).toBe(Array.from(text).slice(0, 2000).join(''));
      fireEvent.click(view.getByRole('button', { name: 'Done' }));
      expect(view.getByText(Array.from(text).slice(0, 2000).join(''))).toBeVisible();
    },
  );

  it('shows a counter from eighty percent and Escape restores the original after an over-limit paste', () => {
    const backend = fakeBackend({ [KEY]: 'x'.repeat(500) });
    const { view, kit } = mount(field(), { backend });
    const textarea = edit(view);
    expect((textarea as HTMLInputElement | HTMLTextAreaElement).value).toBe('x'.repeat(500));
    type(textarea, 'x'.repeat(1500));
    expect(view.queryByText('1500/2000')).toBeNull();
    type(textarea, 'x'.repeat(1600));
    expect(view.getByText('1600/2000')).toBeVisible();
    type(textarea, 'x'.repeat(2100));
    fireEvent.keyDown(textarea, { key: 'Escape' });
    expect(view.queryByRole('textbox')).toBeNull();
    expect(view.getByText('x'.repeat(500))).toBeVisible();
    expect(kit.backend.data.get(KEY)).toBe('x'.repeat(500));
  });

  it('keeps the words in memory and says storage is unavailable when the browser refuses the write', () => {
    const { view, kit } = mount(field(), { backend: blockedBackend() });
    const textarea = edit(view);
    type(textarea, 'only in memory');
    expect(view.getByText('Browser storage unavailable')).toBeVisible();
    expect(kit.controls.memo.read(KEY)).toBe('only in memory');
    fireEvent.click(view.getByRole('button', { name: 'Done' }));
    expect(view.getByText('only in memory')).toBeVisible();
  });

  it('closes on Done keeping what was typed, and returns focus to Edit rather than the page', async () => {
    const { view } = mount(field());
    const textarea = edit(view);
    type(textarea, 'kept');
    fireEvent.click(view.getByRole('button', { name: 'Done' }));
    await settle();
    expect(view.queryByRole('textbox')).toBeNull();
    expect(view.getByText('kept')).toBeVisible();
    expect(document.activeElement).toBe(view.getByRole('button', { name: 'Edit OUTCOME' }));
  });

  it('restores the words held when editing began on Escape, in the field or on Done, without an announcement', async () => {
    const backend = fakeBackend({ [KEY]: 'original' });
    const { view, kit } = mount(field(), { backend });
    const textarea = edit(view);
    type(textarea, 'half typed');
    expect(backend.data.get(KEY)).toBe('half typed');
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    act(() => {
      textarea.dispatchEvent(escape);
    });
    await settle();
    expect(escape.defaultPrevented).toBe(true);
    expect(backend.data.get(KEY)).toBe('original');
    expect(view.queryByRole('textbox')).toBeNull();
    expect(view.getByText('original')).toBeVisible();
    expect(kit.announced).toEqual([]);

    edit(view);
    type(view.getByRole('textbox'), 'again');
    const done = view.getByRole('button', { name: 'Done' });
    const fromDone = new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      done.dispatchEvent(fromDone);
    });
    expect(backend.data.get(KEY)).toBe('original');
    expect(view.queryByRole('textbox')).toBeNull();
  });

  it("keeps Escape inside the editor from reaching the page's own Escape handler", () => {
    const { view } = mount(field());
    const textarea = edit(view);
    const seen = vi.fn();
    document.addEventListener('keydown', seen);
    act(() => {
      textarea.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
      );
    });
    document.removeEventListener('keydown', seen);
    expect(seen).not.toHaveBeenCalled();
  });

  it('survives unrelated updates with the same node, focus, caret and typed text', () => {
    function Page() {
      const [tick, setTick] = useState(0);
      return (
        <div data-tick={tick}>
          <button type="button" onClick={() => setTick(tick + 1)}>
            tick
          </button>
          {field()}
        </div>
      );
    }
    const { view } = mount(<Page />);
    const textarea = edit(view);
    type(textarea, 'hello brave world');
    textarea.setSelectionRange(6, 11);
    act(() => view.getByRole('button', { name: 'tick' }).click());
    act(() => view.getByRole('button', { name: 'tick' }).click());
    expect(view.getByRole('textbox')).toBe(textarea);
    expect(document.activeElement).toBe(textarea);
    expect([textarea.selectionStart, textarea.selectionEnd]).toEqual([6, 11]);
    expect(textarea.value).toBe('hello brave world');
  });

  it('remounts still editing with the typed words from memory, not the older stored ones', () => {
    const backend = fakeBackend({ [KEY]: 'stored' });
    const { view, rerender, kit } = mount(field(), { backend });
    const textarea = edit(view);
    type(textarea, 'typed since');
    rerender(<p>another view</p>);
    expect(view.queryByRole('textbox')).toBeNull();
    // A storage write that lands elsewhere cannot override what this tab typed.
    backend.data.set(KEY, 'someone else');
    rerender(field());
    expect((view.getByRole('textbox') as HTMLTextAreaElement).value).toBe('typed since');
    expect(kit.controls.memoEditing.get()?.key).toBe(KEY);
  });

  it("edits one field at a time and keeps the other's words apart", () => {
    const { view, kit } = mount(
      <>
        {field('outcome')}
        {field('focus')}
      </>,
    );
    fireEvent.click(view.getByRole('button', { name: 'Edit OUTCOME' }));
    type(view.getByRole('textbox'), 'the outcome');
    fireEvent.click(view.getByRole('button', { name: 'Edit FOCUS' }));
    expect(view.getAllByRole('textbox')).toHaveLength(1);
    type(view.getByRole('textbox'), 'the focus');
    expect(kit.backend.data.get(KEY)).toBe('the outcome');
    expect(kit.backend.data.get(FOCUS_KEY)).toBe('the focus');
  });

  it('opens from outside the field, as the More menu does, and focuses it once', () => {
    const { view, kit } = mount(field());
    act(() => kit.controls.startMemoEdit(KEY));
    expect(document.activeElement).toBe(view.getByRole('textbox'));
    expect(kit.controls.memoEditing.get()?.fresh).toBe(false);
  });
});
