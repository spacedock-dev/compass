import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HeldCorrection } from './correction';
import { attachEditor } from './editor';
import {
  CORRECTION_CAP,
  CORRECTION_COMPOSITION_REFUSED,
  CORRECTION_EDIT_REFUSED,
  CORRECTION_UNDO_UNAVAILABLE,
} from './sentences';
import { createDriftState, type DriftCtx } from './state';

/* The correction box's native-editor glue, over a real textarea in jsdom. jsdom has no undo stack, so what is
   proven here is the page's own decisions: what a composition that crosses the 4,216 code point cap leaves in
   the box and in the held draft, and what is said when the browser cannot undo it. That the browser's own undo
   history, caret and composition survive is `drift-parity.mjs`'s, in Chromium. */

const KEY = 'claude:sid-1';
const ROOM = 'a'.repeat(CORRECTION_CAP - 10);

interface Rig {
  readonly input: HTMLTextAreaElement;
  readonly held: HeldCorrection;
  readonly counts: number[];
  readonly said: string[];
  readonly detach: () => void;
  readonly drift: DriftCtx['drift'];
}

function held(text: string): HeldCorrection {
  return {
    id: 1,
    open: true,
    pending: false,
    parts: null,
    text,
    edited: false,
    why: '',
    cue: '',
    stamp: null,
    cited: null,
    failed: null,
  };
}

function rig(text = ROOM): Rig {
  const said: string[] = [];
  const shell = {
    clock: {
      now: () => 0,
      setTimeout: (run: () => void) => setTimeout(run, 0),
      clearTimeout: (handle: ReturnType<typeof setTimeout>) => clearTimeout(handle),
    },
    announcer: {
      forget: vi.fn(),
      announce: (_name: string, sentence: string) => said.push(sentence),
    },
  } as unknown as DriftCtx['shell'];
  const drift = createDriftState(shell);
  const draft = held(text);
  drift.corrections.set(KEY, draft);
  const input = document.createElement('textarea');
  input.value = text;
  document.body.append(input);
  const counts: number[] = [];
  const detach = attachEditor({ drift, shell } as unknown as DriftCtx, KEY, input, {
    onCount: (count) => counts.push(count),
  });
  return { input, held: draft, counts, said, detach, drift };
}

/* A composition as an input method delivers it: it starts, the box fills with provisional text, and it ends. */
function compose(r: Rig, provisional: string): void {
  r.input.dispatchEvent(new Event('compositionstart', { bubbles: true }));
  r.input.value = provisional;
  r.input.dispatchEvent(new Event('compositionend', { bubbles: true }));
}

const stubs: Array<() => void> = [];
function stubExecCommand(run: (command: string) => boolean): void {
  const original = Object.getOwnPropertyDescriptor(document, 'execCommand');
  Object.defineProperty(document, 'execCommand', { configurable: true, value: run });
  stubs.push(() => {
    if (original) Object.defineProperty(document, 'execCommand', original);
    else Reflect.deleteProperty(document, 'execCommand');
  });
}

afterEach(() => {
  for (const restore of stubs.splice(0)) restore();
  document.body.replaceChildren();
});

describe('a composition that crosses the 4,216 code point cap', () => {
  it('keeps none of the inserted text, in the box or in the held draft, and says so', () => {
    const r = rig();
    compose(r, ROOM + '😀'.repeat(20));
    expect(r.input.value).toBe(ROOM);
    expect(r.held.text).toBe(ROOM);
    expect(r.held.edited).toBe(false);
    expect(r.held.compositionRefused).toBe(ROOM);
    expect(r.counts.at(-1)).toBe(CORRECTION_CAP - 10);
    r.detach();
  });

  it('counts code points as the server does, so astral text is not cut on one side only', () => {
    const r = rig('');
    // 1,001 astral characters are 2,002 UTF-16 units but 1,001 code points: well under the cap.
    compose(r, '😀'.repeat(1001));
    expect(r.held.text).toBe('😀'.repeat(1001));
    expect(r.held.edited).toBe(true);
    expect(r.held.compositionRefused).toBeUndefined();
    r.detach();
  });

  it('accepts a composition that reaches the cap exactly', () => {
    const r = rig();
    compose(r, ROOM + 'あ'.repeat(10));
    expect(r.held.text).toBe(ROOM + 'あ'.repeat(10));
    expect(r.held.edited).toBe(true);
    expect(r.held.editWhy).toBe('');
    r.detach();
  });

  it('refuses one code point past it', () => {
    const r = rig();
    compose(r, ROOM + 'あ'.repeat(11));
    expect(r.input.value).toBe(ROOM);
    expect(r.held.text).toBe(ROOM);
    r.detach();
  });

  it('leaves an edit the reader had already made marked as edited', () => {
    const r = rig();
    r.held.edited = true;
    compose(r, ROOM + 'あ'.repeat(40));
    expect(r.held.edited).toBe(true);
    expect(r.held.text).toBe(ROOM);
    r.detach();
  });
});

describe('the refusal says whether the browser could undo it', () => {
  it('names the restore when the browser has no native undo (assignment loses its undo history)', () => {
    const r = rig();
    compose(r, ROOM + 'あ'.repeat(40));
    expect(r.held.editWhy).toBe(`${CORRECTION_COMPOSITION_REFUSED} ${CORRECTION_UNDO_UNAVAILABLE}`);
    expect(r.said).toEqual([r.held.editWhy]);
    r.detach();
  });

  it('keeps the browser’s own undo and stays quiet about it when native undo restores the text', () => {
    const r = rig();
    r.input.focus();
    stubExecCommand((command) => {
      if (command !== 'undo') return false;
      r.input.value = ROOM;
      return true;
    });
    compose(r, ROOM + 'あ'.repeat(40));
    expect(r.input.value).toBe(ROOM);
    expect(r.held.editWhy).toBe(CORRECTION_COMPOSITION_REFUSED);
    expect(r.held.restoring).toBe(false);
    r.detach();
  });

  it('never lets a native undo that restored something else stand', () => {
    const r = rig();
    r.input.focus();
    stubExecCommand((command) => {
      if (command !== 'undo') return false;
      r.input.value = 'something older';
      return true;
    });
    compose(r, ROOM + 'あ'.repeat(40));
    expect(r.input.value).toBe(ROOM);
    expect(r.held.text).toBe(ROOM);
    expect(r.held.editWhy).toContain(CORRECTION_UNDO_UNAVAILABLE);
    r.detach();
  });

  it('holds the box’s own text when the refusal is a plain edit, not a composition', () => {
    const r = rig();
    r.input.value = ROOM + 'b'.repeat(40);
    r.input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(r.input.value).toBe(ROOM);
    expect(r.held.text).toBe(ROOM);
    expect(r.held.editWhy).toBe(`${CORRECTION_EDIT_REFUSED} ${CORRECTION_UNDO_UNAVAILABLE}`);
    r.detach();
  });
});
