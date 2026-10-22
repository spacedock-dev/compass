import { describe, expect, it } from 'vitest';
import { driftReasons, liveTokens } from './level';
import { readScopeLine } from './sentences';

/* Malformed analysis data may name a token the page never registered, including names every plain object
   inherits. Those must render nothing and throw nothing: the page reads only the closed tables. */
const INHERITED = ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'valueOf'];
const NONE = { first: '', blockers: [] };

function reasons(level: string, tokens: unknown) {
  return driftReasons(level, tokens, [], [], new Map(), new Set(), 0);
}

describe('unknown and inherited reason tokens', () => {
  it.each(INHERITED)('renders no explanation for %s on a live or analysis level', (token) => {
    expect(() => reasons('medium', [token])).not.toThrow();
    expect(reasons('medium', [token])).toEqual(NONE);
    expect(reasons('high', [token, 'unknown-token'])).toEqual(NONE);
  });

  it('renders no blocker for inherited names when the level is not enough', () => {
    expect(reasons('not_enough', INHERITED)).toEqual(NONE);
  });

  it('keeps the registered explanation when an inherited name sits beside it', () => {
    expect(reasons('high', ['constructor', 'pass-then-write'])).toEqual({
      first: 'A check passed, then files were written after it.',
      blockers: [],
    });
    expect(reasons('not_enough', ['__proto__', 'no-passing-check'])).toEqual({
      first: '',
      blockers: ['No check has passed yet.'],
    });
  });

  it('drops inherited names from the live token set', () => {
    expect(liveTokens(['constructor', '__proto__', 'failed-check'])).toEqual(['failed-check']);
  });

  it('falls back to the producer text for an inherited scope name', () => {
    expect(readScopeLine('constructor', 'Producer words.')).toBe('Producer words.');
    expect(readScopeLine('__proto__', 'Producer words.')).toBe('Producer words.');
    expect(readScopeLine('final', 'Producer words.')).toBe('Everything up to the session’s end.');
  });
});

describe('registered reasons keep their explanation and level', () => {
  it.each([
    ['failed-check', 'A failed check is counted but its entry is not listed.'],
    ['departure', 'The model assessed a departure from your intent.'],
    ['claim-contradicted', 'The record contradicts what the agent said.'],
    ['claim-not-shown', 'The record read does not show what the agent said.'],
    ['pass-then-write', 'A check passed, then files were written after it.'],
    ['writes-outside-folders', 'Some files were written outside the folders your intent names.'],
    [
      'most-writes-outside-folders',
      'Most files were written outside the folders your intent names.',
    ],
  ])('%s reads its registered line at a drawn level', (token, line) => {
    const result = reasons('high', [token]);
    expect(result.blockers).toEqual([]);
    expect(result.first).toBe(line);
  });

  it.each([
    'no-passing-check',
    'check-not-recorded',
    'background-run',
    'command-after-pass',
    'pass-older-than-read',
    'later-direction',
    'entries-not-listed',
  ])('%s is held back as a blocker at not_enough', (token) => {
    const result = reasons('not_enough', [token]);
    expect(result.first).toBe('');
    expect(result.blockers).toHaveLength(1);
    expect(result.blockers[0]).not.toBe('');
  });

  it('keeps the not_enough level text for an intent that names no folder out of the blockers', () => {
    expect(reasons('not_enough', ['intent-names-no-folder'])).toEqual(NONE);
  });
});
