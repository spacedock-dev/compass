import { describe, expect, it } from 'vitest';
import { mountProject } from './testing';

/* Keyboard focus on the Projects list is kept by the member button's own node surviving a refresh (see the
   Keyboard focus row of docs/design-reader-state.md), so a member line's key must not move when another
   session joins above it. */

const session = (sid: string, state: string, last: number) => ({
  harness: 'codex',
  sid,
  project: 'alpha/app',
  title: `Session ${sid}`,
  state,
  active: state === 'working',
  last_activity: last,
});

const member = (sid: string): HTMLElement => {
  const found = document.querySelector<HTMLElement>(
    `button.next-project-session[data-next-session="${sid}"]`,
  );
  if (!found) throw new Error(`No member line for ${sid}.`);
  return found;
};

describe('the Projects list keeps a member line through a refresh', () => {
  it('keeps keyboard focus on a member when a session joins above it', async () => {
    const page = mountProject({
      hash: '#n=projects',
      data: {
        generated: 1000,
        sessions: [session('s1', 'working', 990), session('s2', 'idle', 980)],
      },
    });
    await page.settle();
    const focused = member('s2');
    focused.focus();
    await page.poll({
      generated: 1010,
      sessions: [
        session('s1', 'working', 990),
        session('s2', 'idle', 980),
        session('s3', 'needs_input', 1005),
      ],
    });
    const lines = [...document.querySelectorAll('button.next-project-session')].map((line) =>
      line.getAttribute('data-next-session'),
    );
    expect(lines).toEqual(['s3', 's1', 's2']);
    expect(member('s2')).toBe(focused);
    expect(document.activeElement).toBe(focused);
  });

  it('draws both lines of a harness and sid the board published twice', async () => {
    const page = mountProject({
      hash: '#n=projects',
      data: {
        generated: 1000,
        sessions: [session('s1', 'working', 990), session('s1', 'working', 980)],
      },
    });
    await page.settle();
    expect(document.querySelectorAll('button.next-project-session')).toHaveLength(2);
  });
});
