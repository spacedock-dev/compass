// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createShell } from './createShell';

function mediaWith(reduced: boolean) {
  return (query: string) =>
    ({
      matches: query.includes('prefers-reduced-motion') && reduced,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }) as unknown as MediaQueryList;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the shell reads the reader's motion preference from the browser", () => {
  it.each([
    ['holds a background paint for the toggle motion when motion is allowed', false, true],
    ['holds nothing when the reader asked for reduced motion', true, false],
  ])('%s', async (_name, reduced, held) => {
    vi.useFakeTimers();
    vi.stubGlobal('matchMedia', mediaWith(reduced));
    const shell = createShell();
    shell.display.noteToggle();
    shell.runtime.store.acceptData({ generated: 5, sessions: [] }, '1.5');
    let painted = false;
    void shell.display.paint({ manual: false, accepted: true }).then(() => {
      painted = true;
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(painted).toBe(!held);
    await vi.advanceTimersByTimeAsync(400);
    expect(painted).toBe(true);
    expect(shell.display.getSnapshot().data?.generated).toBe(5);
  });
});
