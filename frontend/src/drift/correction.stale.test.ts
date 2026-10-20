import { describe, expect, it } from 'vitest';
import type { Annotation } from '../intent/annotation';
import { correctionStale, correctionStamp, type HeldCorrection } from './correction';

/* A correction held open while the reader marks the reading Not accurate carried the withdrawn departure
   and, since 2026-10-20, Compass's explanation of it: marking moved none of the stamp's three inputs. */
const annotation = {
  revision: 2,
  settled_through: null,
  assessment: { read_at: 150 },
} as unknown as Annotation;

function held(stamp: string): HeldCorrection {
  return {
    id: 1,
    open: true,
    pending: false,
    parts: ['Back to my goal: Ship it'],
    text: null,
    edited: false,
    why: '',
    cue: '',
    stamp,
    cited: null,
    failed: null,
  };
}

describe('a correction held across Not accurate', () => {
  it('keeps the legacy stamp until the reading is marked', () => {
    expect(correctionStamp(annotation)).toBe('[2,null,150]');
    expect(correctionStamp({ ...annotation, not_accurate: false } as Annotation)).toBe(
      '[2,null,150]',
    );
  });

  it('is stale once the reading it was composed from is marked Not accurate', () => {
    const open = held(correctionStamp(annotation));
    expect(correctionStale(open, annotation, null, null)).toBe(false);
    const marked = { ...annotation, not_accurate: true } as Annotation;
    expect(correctionStale(open, marked, null, null)).toBe(true);
  });

  it('is not stale again once recomposed after the mark', () => {
    const marked = { ...annotation, not_accurate: true } as Annotation;
    expect(correctionStale(held(correctionStamp(marked)), marked, null, null)).toBe(false);
  });
});
