import { act, fireEvent, screen } from '@testing-library/react';
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
                  provider: harness === 'pi' ? 'codex' : 'claude',
                  label: harness === 'pi' ? 'Codex' : 'Claude Code',
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
      expect(popup.textContent).toContain('1. Give the goal.');
      expect(popup.textContent).toContain('Expected outcome is optional.');
      expect(popup.textContent).not.toContain('a level needs one');
      // Where a detected goal comes from, and that it stands until the reader edits it.
      expect(popup.textContent).toContain(
        "A session's /goal is used until you edit it; else Compass drafts from your first prompt.",
      );
      expect(popup.textContent).toContain('A progress check asks once to allow reading');
      expect(popup.textContent).toContain('3. Read where the work left your goal.');
      expect(popup.textContent).toContain('Progress levels: Claude Code, Codex and Pi only.');
      expect(popup.textContent).toContain(
        reader
          ? `Reader here: ${harness === 'pi' ? 'Codex' : 'Claude Code'}.`
          : 'Reader here: No reader on this machine.',
      );
      expect(popup.textContent).toContain(
        steer ? 'Steer back: available here.' : 'Steer back: Claude Code only.',
      );
      expect(popup.textContent).toContain('Compass never writes into sessions.');
      expect(popup.querySelector('[data-next-intent-howto-no-line]')?.textContent).toBe(
        "With no outcome line, Compass reads your goal's end state; a goal too vague to read is refused.",
      );
      expect(popup.textContent).not.toContain('Not enough recorded yet');
      expect(popup.querySelector('[data-next-intent-howto-settle]')?.textContent).toBe(
        "Readings settle a command's latest unpiped run, failed or passed with nothing written after it. A recorded write breaking a folder limit also departs.",
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
