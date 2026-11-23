import { act, fireEvent, screen, within } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { mountDrift, ROUTE } from '../drift/testing';
import { GLOSSARY } from '../language/glossary';

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

const summary = () => screen.getByRole('button', { name: GLOSSARY.howGoalsWork.plain });
const explanation = () => document.getElementById('goal-explanation');

async function openHowTo(page: { settle: () => Promise<void> }) {
  fireEvent.click(summary());
  await page.settle();
}

describe('the Intent how-to', () => {
  it('keeps one read-only Goal disclosure when annotations are off', async () => {
    const page = mountDrift({ payload: { annotate: false } });
    await page.settle();
    const goal = screen.getByRole('region', { name: GLOSSARY.goal.plain });
    expect(within(goal).getByRole('button', { name: GLOSSARY.howGoalsWork.plain })).toBe(summary());
    expect(within(goal).queryByRole('textbox')).toBeNull();
    await openHowTo(page);
    expect(explanation()).toBeVisible();
    expect(explanation()?.textContent).toContain('Annotations are off for this run.');
    expect(page.gets('/api/annotations')).toBe(0);
    expect(page.posts()).toBe(0);
  });

  it('keeps the one Goal disclosure open across a refresh and a session remount', async () => {
    const page = mountDrift();
    await page.settle();
    await openHowTo(page);
    expect(screen.getByRole('region', { name: GLOSSARY.goal.plain }).contains(summary())).toBe(
      true,
    );
    expect(document.querySelectorAll('#goal-explanation')).toHaveLength(1);
    expect(explanation()).toBeVisible();
    await page.poll(page.state.data);
    expect(summary().getAttribute('aria-expanded')).toBe('true');
    await act(async () => {
      page.router.navigate({ view: 'sessions' });
    });
    await page.settle();
    expect(screen.queryByRole('button', { name: GLOSSARY.howGoalsWork.plain })).toBeNull();
    await act(async () => {
      page.router.navigate({
        view: 'session',
        project: 'alpha/app',
        harness: 'claude',
        session: 's1',
      });
    });
    await page.settle();
    expect(summary().getAttribute('aria-expanded')).toBe('true');
    expect(explanation()).toBeVisible();
    expect(page.posts()).toBe(0);
  });
  for (const [harness, reader, steer] of [
    ['claude', true, true],
    ['codex', true, false],
    ['pi', true, false],
    ['cursor', false, false],
  ] as const) {
    it(`derives the limits for ${harness} from the board`, async () => {
      const page = mountDrift({
        session: { harness },
        hash: `#n=session:alpha%2Fapp:${harness}:s1`,
        payload: {
          reading_routes: {
            [harness]: reader
              ? {
                  ...ROUTE,
                  provider: harness === 'claude' ? 'claude' : 'codex',
                  label: harness === 'claude' ? 'Claude Code' : 'Codex',
                }
              : { provider: '', note: 'No reader on this machine.' },
          },
        },
      });
      await page.settle();
      expect(screen.queryByRole('button', { name: 'What analysis does' })).toBeNull();
      // Not in the card's header, where the design has one word of status: in the quiet menu.
      expect(
        document
          .querySelector('[aria-labelledby="next-session-intent-heading"] header')
          ?.querySelector('[data-slot=popover]'),
      ).toBeNull();
      await openHowTo(page);
      const popup = explanation() as HTMLElement;
      expect(popup.textContent?.trim().split(/\s+/).length).toBeLessThanOrEqual(150);
      expect(popup.textContent).toContain('1. Give the goal.');
      expect(popup.textContent).toContain('Expected outcome is optional.');
      expect(popup.textContent).not.toContain('a level needs one');
      // Where a detected goal comes from, and that it stands until the reader edits it.
      expect(popup.textContent).toContain(
        'Compass uses /goal until edited, or drafts from your first prompt.',
      );
      expect(popup.textContent).toContain('3. To steer back, copy a correction.');
      expect(popup.textContent).toContain(
        'Compass can read recorded work from Claude Code, Codex and Pi.',
      );
      expect(popup.textContent).toContain(
        'Progress levels appear only for Claude Code and Pi sessions.',
      );
      expect(popup.textContent).toContain(
        'A progress check uses AI and counts against a daily cap.',
      );
      expect(popup.textContent).toContain(
        reader
          ? `Reader here: ${harness === 'claude' ? 'Claude Code' : 'Codex'}.`
          : 'Reader here: No reader on this machine.',
      );
      expect(popup.textContent).toContain(
        steer ? 'Steer back: available here.' : 'Steer back: Claude Code only.',
      );
      expect(popup.textContent).toContain('Compass never writes into sessions.');
      expect(popup.querySelector('[data-next-intent-howto-no-line]')?.textContent).toBe(
        'Without outcome lines, the goal needs a specific end state.',
      );
      expect(popup.textContent).not.toContain('Not enough recorded yet');
      expect(popup.querySelector('[data-next-intent-howto-settle]')?.textContent).toBe(
        'The latest unpiped run settles when it fails or passes with no later write. Writes outside folder limits also depart.',
      );
      expect(popup.querySelector('[data-next-intent-howto-accuracy]')?.textContent).toBe(
        "The Claude reader's accuracy check has not passed, and its latest correction is unmeasured, so read a level as an account of the evidence, not a measurement.",
      );
      const node = popup;
      await page.poll(page.state.data);
      expect(explanation()).toBe(node);
      expect(page.posts()).toBe(0);
    });
  }
});
