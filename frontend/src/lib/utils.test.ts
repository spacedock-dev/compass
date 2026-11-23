import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { cn, TYPE_STEPS, RADII } from './utils';

describe('the local class merger', () => {
  it('keeps Compass type sizes beside colours and resolves actual conflicts', () => {
    for (const size of TYPE_STEPS) {
      expect(cn(`text-${size}`, 'text-muted-foreground')).toBe(
        `text-${size} text-muted-foreground`,
      );
      expect(cn('text-foreground', `text-${size}`)).toBe(`text-foreground text-${size}`);
    }
    expect(cn('p-2', false, { 'p-4': true })).toBe('p-4');
    expect(cn('text-body', 'text-label')).toBe('text-label');
    expect(cn('rounded-control', 'rounded-card')).toBe('rounded-card');
    expect(cn('rounded-control', 'rounded-status-tile')).toBe('rounded-status-tile');
  });
  it('knows exactly the type steps and radii the theme declares', () => {
    const theme = readFileSync('frontend/src/styles/tailwind.css', 'utf8');
    const names = (kind: string) =>
      [...theme.matchAll(new RegExp(`--${kind}-([a-z][a-z0-9-]*):`, 'g'))]
        .map((match) => match[1])
        .sort();
    expect(names('text')).toEqual([...TYPE_STEPS].sort());
    expect(names('radius')).toEqual([...RADII].sort());
  });
});
