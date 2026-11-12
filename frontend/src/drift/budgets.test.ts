import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CORRECTION_CAP, CORRECTION_COMPOSITION_REFUSED, STORED_WHY } from './sentences';

describe('the line budgets shared with the runtime', () => {
  it('keeps the frontend correction cap equal to the copy route', () => {
    const runtime = readFileSync(
      'compass/skills/compass/compass_runtime/copied_corrections.py',
      'utf8',
    );
    expect(Number(runtime.match(/^CORRECTION_CAP_CHARS = (\d+)$/m)?.[1])).toBe(CORRECTION_CAP);
    expect(CORRECTION_CAP).toBe(9700);
  });
  it('names the cap it enforces when it refuses a composition', () => {
    expect(CORRECTION_COMPOSITION_REFUSED).toBe(
      'This composition would exceed 9,700 characters and was not kept.',
    );
  });
  it('says why the prompt did not pose the lines', () => {
    expect(STORED_WHY['lines-no-room']).toBe(
      "Not asked: your goal and lines did not fit in this reading's prompt.",
    );
  });
});
