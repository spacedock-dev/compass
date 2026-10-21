import { describe, expect, it } from 'vitest';
import { REGION_IDS } from '../shell/announcer';
import { byAction, driftBoard, mountDrift, press, readingPosts, textOf } from './testing';

/* Whether Analyze can be pressed, as the drawn card last showed it. A change no press caused is said rather
   than silent, but never at once: closing waits for the inert state to hold across two payloads and ten
   seconds, so a session pausing between turns never closes the button. */
const QUIET = {
  ok: false,
  reason: 'idle-unknown',
  sentence: 'The server says the turn is not recorded.',
};
const board = (eligibility: unknown, generated: number) => ({
  ...driftBoard({ session: eligibility ? { reading_eligibility: eligibility } : {} }),
  generated,
});
const inert = () => byAction('reading-ask')?.getAttribute('aria-disabled') === 'true';
const cue = () => document.getElementById(REGION_IDS.cue)?.textContent ?? '';
const change = () => textOf('.next-cockpit-reading-change');

describe('Analyze closing and opening', () => {
  it('holds a close for two payloads and ten seconds, then says it once', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    expect(inert()).toBe(false);
    await page.poll(board(QUIET, 1100));
    expect(inert()).toBe(false);
    // The same moment, a second payload: not yet ten seconds.
    await page.poll(board(QUIET, 1110));
    expect(inert()).toBe(false);
    await page.advance(11_000);
    await page.poll(board(QUIET, 1120));
    expect(inert()).toBe(true);
    expect(change()).toBe('Analyze closed: the session went quiet.');
    expect(cue()).toBe('Analyze closed: the session went quiet.');
    expect(textOf('#next-cockpit-reading-refused')).toBe('Analyze opens while this session runs.');
  });

  it('does not close on the clock alone: the hold waits for a second payload as well', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.poll(board(QUIET, 1100));
    // Ten seconds pass and the card redraws, but no new payload has arrived.
    await page.advance(10_500);
    expect(inert()).toBe(false);
    await page.poll(board(QUIET, 1130));
    expect(inert()).toBe(true);
  });

  it('opens at once, saying so, and holds the next sentence to once a minute', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.poll(board(QUIET, 1100));
    await page.advance(11_000);
    await page.poll(board(QUIET, 1110));
    expect(inert()).toBe(true);
    await page.poll(board(null, 1120));
    expect(inert()).toBe(false);
    // An opening is said to the region and not drawn: the control standing pressable says it in view.
    expect(change()).toBe('');
    // The region already said the close inside the minute, so the open waits for it.
    expect(cue()).toBe('Analyze closed: the session went quiet.');
    await page.advance(61_000);
    expect(cue()).toBe("Analyze is open: the session's last turn finished.");
  });

  it('says nothing for a change that reverts before it commits', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.poll(board(QUIET, 1100));
    await page.poll(board(null, 1110));
    await page.advance(30_000);
    await page.poll(board(null, 1120));
    expect(inert()).toBe(false);
    expect(cue()).toBe('');
    expect(change()).toBe('');
  });

  it("answers a press during a held close with the board's refusal and sends nothing", async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.poll(board(QUIET, 1100));
    expect(inert()).toBe(false);
    await press(byAction('reading-ask'));
    expect(readingPosts(page)).toEqual([]);
    expect(textOf('#next-cockpit-reading-refused')).toContain(
      'Analyze opens while this session runs',
    );
    // The press learned the board's state, so the card shows it without a change line.
    expect(inert()).toBe(true);
    expect(change()).toBe('');
  });

  it('takes the change line down after thirty seconds', async () => {
    const page = mountDrift({});
    await page.settle();
    await page.settle();
    await page.poll(board(QUIET, 1100));
    await page.advance(11_000);
    await page.poll(board(QUIET, 1110));
    expect(change()).not.toBe('');
    await page.advance(31_000);
    expect(change()).toBe('');
  });
});
