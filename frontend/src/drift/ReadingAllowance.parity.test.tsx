/* The terminal's `--drift` prints the allowance this card draws, before a spending press. One fixture holds
   each route preview and the lines the page draws for it; this test renders the page's own component over
   every case, and `test_terminal_drift.py` holds the Python port to the same file. The page is the oracle:
   when this fails, the fixture is corrected from the page, never from the port. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ReadingAllowance } from './ReadingAllowance';

interface AllowanceCase {
  readonly name: string;
  readonly capacity: unknown;
  readonly lines: readonly string[];
}

const fixture = JSON.parse(
  // From the repository root, as `Page.test.tsx` reads: under jsdom `import.meta.url` is not a file URL.
  readFileSync(resolve(process.cwd(), 'frontend/test/fixtures/prompt-allowance.json'), 'utf8'),
) as { readonly cases: readonly AllowanceCase[] };

afterEach(cleanup);

describe('the allowance the terminal prints before it spends', () => {
  it('names every reason the server can publish', () => {
    const reasons = new Set(
      fixture.cases.map((each) =>
        typeof each.capacity === 'object' && each.capacity !== null
          ? (each.capacity as Record<string, unknown>)['reason']
          : undefined,
      ),
    );
    for (const reason of [
      'estimated',
      'context-config',
      'context-no-room',
      'context-dynamic',
      'context-compaction',
      'context-fallback',
      'unavailable',
    ]) {
      expect(reasons.has(reason)).toBe(true);
    }
  });

  it.each(fixture.cases.map((each) => [each.name, each] as const))(
    'reads as the page draws it: %s',
    (_name, each) => {
      const { container } = render(<ReadingAllowance route={{ capacity: each.capacity }} />);
      const drawn = [...container.querySelectorAll('[data-next-reading-allowance] p')].map(
        (paragraph) => paragraph.textContent,
      );
      expect(drawn).toEqual(each.lines);
    },
  );
});
