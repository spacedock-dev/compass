import { correctionFit, correctionLength, type HeldCorrection } from './correction';
import {
  CORRECTION_CAP,
  CORRECTION_COMPOSITION_REFUSED,
  CORRECTION_EDIT_REFUSED,
  CORRECTION_UNDO_UNAVAILABLE,
} from './sentences';
import type { DriftCtx } from './state';

/* The correction's native editor, as the browser edits it. A textarea keeps its own caret, selection, undo
   history and input-method composition for as long as the same node stays in the document, so everything
   here exists to keep that true while the page enforces a cap the browser does not know about: the 5,900
   code points the copy route accepts.

   The cap is enforced before the browser inserts, through its own edit command, so the insertion stays in
   the browser's undo transaction; assigning `.value` afterwards erased the preceding edit as well (measured
   in Chrome). A composition is never cut or copied while it is provisional: its words become the reader's
   only when it ends. The legacy cockpit's document-level handlers are the oracle, and
   `drift-parity.mjs` drives the real thing in Chromium, because none of this can be shown in a DOM that has no
   undo stack. */

type Native = (command: string, text?: string) => boolean;

function nativeCommand(input: HTMLTextAreaElement): Native {
  return (command, text) => {
    if (input.ownerDocument.activeElement !== input) return false;
    const run = (input.ownerDocument as { execCommand?: (...args: unknown[]) => boolean })
      .execCommand;
    if (typeof run !== 'function') return false;
    try {
      return run.call(input.ownerDocument, command, false, text);
    } catch {
      return false;
    }
  };
}

export interface EditorHooks {
  /** The count under the box, from the node's own value, provisional composition text included. */
  readonly onCount: (count: number) => void;
}

/* Attaches the editor's listeners to its node and, for as long as it is mounted, the document-level ones that
   keep the Drift card from redrawing under a pointer on its way to a control. Returns the detach function. */
export function attachEditor(
  ctx: DriftCtx,
  key: string,
  input: HTMLTextAreaElement,
  hooks: EditorHooks,
): () => void {
  const { drift, shell } = ctx;
  const { editor } = drift;
  const native = nativeCommand(input);
  const heldOf = (): HeldCorrection | undefined => drift.corrections.get(key);

  const refused = (held: HeldCorrection, why: string): void => {
    held.editWhy = why;
    hooks.onCount(correctionLength(input.value));
    const name = `correction-edit:${key}`;
    shell.announcer.forget(name);
    shell.announcer.announce(name, why);
    drift.notify();
  };

  /* Native undo may synchronously publish input. A mismatched undo must never replace the held draft with the
     text being refused. */
  const restore = (before: string, start: number | null, end: number | null): boolean => {
    const held = heldOf();
    let undone = false;
    if (held) held.restoring = true;
    try {
      undone = native('undo') && input.value === before;
    } finally {
      if (held) held.restoring = false;
    }
    /* A browser without native undo still keeps every pre-composition word. Assignment loses its undo
       history, so that fallback says so. */
    if (!undone) input.value = before;
    if (typeof start === 'number')
      input.setSelectionRange(start, typeof end === 'number' ? end : start);
    return undone;
  };

  /* Intercept before the browser inserts an over-cap run. Paste needs its own event: a textarea's
     `beforeinput` may carry no paste data. */
  const insert = (event: Event, text: string): void => {
    if (editor.composition || (event as InputEvent).isComposing) return;
    const held = heldOf();
    if (!held || event.cancelable === false) return;
    const before = String(input.value || '');
    const start = typeof input.selectionStart === 'number' ? input.selectionStart : before.length;
    const end = typeof input.selectionEnd === 'number' ? input.selectionEnd : start;
    const typed = before.slice(0, start) + text + before.slice(end);
    const fitted = correctionFit(before, typed, start + text.length);
    if (!fitted) return;
    event.preventDefault();
    if (fitted.value === before) return;
    const tail = before.slice(end);
    const inserted = fitted.value.slice(start, fitted.value.length - tail.length);
    let accepted = false;
    held.restoring = true;
    try {
      accepted = native('insertText', inserted);
    } finally {
      held.restoring = false;
    }
    if (accepted && input.value === fitted.value) {
      held.text = fitted.value;
      held.edited = true;
      held.cue = '';
      held.editWhy = '';
      hooks.onCount(correctionLength(input.value));
      drift.notify();
      return;
    }
    const undone = input.value === before || restore(before, start, end);
    refused(held, CORRECTION_EDIT_REFUSED + (undone ? '' : ` ${CORRECTION_UNDO_UNAVAILABLE}`));
  };

  const onPaste = (event: ClipboardEvent): void => {
    if (!event.clipboardData) return;
    insert(event, event.clipboardData.getData('text/plain'));
  };

  const onBeforeInput = (event: InputEvent): void => {
    if (event.isComposing || editor.composition) return;
    const kind = String(event.inputType || '');
    if (kind === 'insertFromPaste' || !kind.startsWith('insert')) return;
    if (kind === 'insertLineBreak' || kind === 'insertParagraph') {
      insert(event, '\n');
      return;
    }
    const text =
      typeof event.data === 'string'
        ? event.data
        : event.dataTransfer && typeof event.dataTransfer.getData === 'function'
          ? event.dataTransfer.getData('text/plain')
          : null;
    if (text !== null) {
      insert(event, text);
      return;
    }
    const held = heldOf();
    if (held && event.cancelable !== false) {
      event.preventDefault();
      refused(held, CORRECTION_EDIT_REFUSED);
    }
  };

  /* The correction box, edited in place with no redraw of the box itself. Capped at the copy route's 5,900
     characters, counted as the server counts them, cut from what the edit inserted and never from the text
     already there; an edit makes the text the reader's own and clears the Copy cue, which described the text
     before it. */
  const onInput = (event: Event): void => {
    hooks.onCount(correctionLength(input.value));
    if ((event as InputEvent).isComposing || editor.composition?.input === input) return;
    const held = heldOf();
    if (!held || held.restoring) return;
    const typed = String(input.value || '');
    if (held.compositionRefused === typed) return;
    delete held.compositionRefused;
    const before = typeof held.text === 'string' ? held.text : String(input.defaultValue || '');
    if (correctionLength(typed) > CORRECTION_CAP) {
      const undone = restore(before, before.length, before.length);
      refused(held, CORRECTION_EDIT_REFUSED + (undone ? '' : ` ${CORRECTION_UNDO_UNAVAILABLE}`));
      return;
    }
    held.text = typed;
    held.edited = true;
    held.cue = '';
    held.editWhy = '';
    drift.notify();
  };

  const onCompositionStart = (): void => {
    const held = heldOf();
    if (!held) return;
    editor.composition = {
      input,
      held,
      before: String(input.value || ''),
      edited: held.edited,
      start: input.selectionStart,
      end: input.selectionEnd,
    };
    drift.notify();
  };

  const onCompositionEnd = (event: Event): void => {
    const composition = editor.composition;
    if (!composition || event.target !== composition.input) return;
    editor.composition = null;
    const { held, before, start, end } = composition;
    if (correctionLength(input.value) > CORRECTION_CAP) {
      const undone = restore(before, start, end);
      held.text = before;
      held.edited = composition.edited;
      held.compositionRefused = before;
      refused(
        held,
        CORRECTION_COMPOSITION_REFUSED + (undone ? '' : ` ${CORRECTION_UNDO_UNAVAILABLE}`),
      );
    } else if (input.value !== before) {
      held.text = input.value;
      held.edited = true;
      held.cue = '';
      held.editWhy = '';
    }
    hooks.onCount(correctionLength(input.value));
    /* Browsers may publish the final input after compositionend. Let that update the held draft before
       drawing a payload received during the edit. */
    resume();
  };

  const onFocus = (): void => {
    editor.focused = key;
    drift.notify();
  };

  const onBlur = (): void => {
    if (editor.focused === key) editor.focused = null;
    const held = heldOf();
    if (held) held.paintWhy = '';
    resume();
  };

  /* A paint the editing queued is released after the work that caused its wait has finished: a microtask, so
     the final input event a browser publishes after a composition lands first, and never while a pointer is
     still on its way to a control. */
  function resume(): void {
    queueMicrotask(() => {
      if (editor.pointer) return;
      drift.notify();
    });
  }

  /* Blur runs between pointer down and click. Replacing the pressed control there swallowed Chrome's first
     Copy. Wait for dispatch, not a timer: a reader may hold the pointer down longer than any guessed delay. */
  const doc = input.ownerDocument;
  const view = doc.defaultView;
  const pointerDone = (): void => {
    editor.pointer = null;
    resume();
  };
  const onPointerDown = (event: PointerEvent): void => {
    if (event.button !== 0 || event.isPrimary === false) return;
    if (event.target instanceof Node && input.contains(event.target)) return;
    if (doc.activeElement !== input) return;
    if (!heldOf()) return;
    const target =
      event.target instanceof Element
        ? (event.target.closest('button,a,summary,[role=button]') ?? event.target)
        : event.target;
    editor.pointer = { id: event.pointerId, target, key };
  };
  const onClick = (): void => {
    if (!editor.pointer) return;
    /* Listener microtask checkpoints may precede the bubble action handler. */
    shell.clock.setTimeout(pointerDone, 0);
  };
  const onPointerUp = (event: PointerEvent): void => {
    const pointer = editor.pointer;
    if (!pointer || event.pointerId !== pointer.id) return;
    const target = pointer.target;
    if (
      target === event.target ||
      (target instanceof Node && event.target instanceof Node && target.contains(event.target))
    ) {
      return;
    }
    pointerDone();
  };
  const onPointerCancel = (event: PointerEvent): void => {
    if (editor.pointer && event.pointerId === editor.pointer.id) pointerDone();
  };
  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Tab' && editor.pointer) pointerDone();
  };

  /* A box that already holds focus when it is attached (the press that opened it asked for focus) is focused
     before any listener could have heard it. */
  if (doc.activeElement === input) editor.focused = key;
  input.addEventListener('paste', onPaste);
  input.addEventListener('beforeinput', onBeforeInput);
  input.addEventListener('input', onInput);
  input.addEventListener('compositionstart', onCompositionStart);
  input.addEventListener('compositionend', onCompositionEnd);
  input.addEventListener('focus', onFocus);
  input.addEventListener('blur', onBlur);
  doc.addEventListener('pointerdown', onPointerDown, true);
  doc.addEventListener('click', onClick, true);
  doc.addEventListener('pointerup', onPointerUp, true);
  doc.addEventListener('pointercancel', onPointerCancel, true);
  doc.addEventListener('keydown', onKeyDown, true);
  view?.addEventListener('blur', pointerDone);
  return () => {
    input.removeEventListener('paste', onPaste);
    input.removeEventListener('beforeinput', onBeforeInput);
    input.removeEventListener('input', onInput);
    input.removeEventListener('compositionstart', onCompositionStart);
    input.removeEventListener('compositionend', onCompositionEnd);
    input.removeEventListener('focus', onFocus);
    input.removeEventListener('blur', onBlur);
    doc.removeEventListener('pointerdown', onPointerDown, true);
    doc.removeEventListener('click', onClick, true);
    doc.removeEventListener('pointerup', onPointerUp, true);
    doc.removeEventListener('pointercancel', onPointerCancel, true);
    doc.removeEventListener('keydown', onKeyDown, true);
    view?.removeEventListener('blur', pointerDone);
    // The node is leaving the document, so nothing it was holding is held any longer.
    if (editor.pointer?.key === key) editor.pointer = null;
    if (editor.composition?.input === input) editor.composition = null;
    if (editor.focused === key) editor.focused = null;
    drift.notify();
  };
}
