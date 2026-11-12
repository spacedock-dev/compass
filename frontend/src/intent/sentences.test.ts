import { describe, expect, it } from 'vitest';
import { goalOverLimit, lineOverLimit, saveRefusal } from './sentences';

describe('the over-limit and refusal sentences', () => {
  it('group their numbers as the rest of the page does', () => {
    expect(goalOverLimit(1100, 1000)).toBe('The goal is 1,100 characters; the limit is 1,000.');
    expect(lineOverLimit(2, 1286, 800)).toBe('Line 2 is 1,286 characters; the limit is 800.');
    expect(saveRefusal({ code: 'line_too_long', line: 2, length: 1286, cap: 800 })).toBe(
      'Not saved: line 2 is 1,286 characters; the limit is 800.',
    );
  });
});
