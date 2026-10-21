import { openSelect, chooseSelect } from '../../test/select';
import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { clock } from '../observed';
import { openPendingDirection } from './api';
import { json } from './testing';
import {
  board,
  control,
  goalBox,
  inert,
  lineBoxes,
  mountSession,
  stored,
  text,
  type,
} from './panel.testing';

/* Later directions: what the reader said after saving their words, asked about before a reading is spent.
   Add opens one for review as a pending line, Keep settles every direction it was shown, and neither
   decides whether a direction conflicts. */

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null) => {
  await act(async () => {
    fireEvent.click(button as Element);
  });
};

const fact = (id: string, at: number, summary: string, extra: Record<string, unknown> = {}) => ({
  fact_id: id,
  type: 'user_message',
  by: 'person:me',
  summary,
  at,
  source_session: { harness: 'claude', sid: 's1' },
  ...extra,
});
const record =
  (...facts: unknown[]) =>
  () =>
    json({ semantic: { facts } });

/* What the reader's presses sent: the read of every open direction's words that starts when the question is
   drawn is not a press. */
const presses = (page: {
  allPosts: () => { path: string; body?: Record<string, unknown> | null }[];
}) => page.allPosts().filter((p) => !(p.path === '/api/direction' && p.body?.['fact_ids']));

const SAVED = { goal: 'Ship the worker', revision: 1 };
const SAVED_AT = { annotation_goal_saved_at: 500, annotation_at: 500 };
const ONE = [fact('f1', 600, 'Do it the careful way')];

describe('the question before the press', () => {
  it('quotes a later direction under the time it was said, in the Analyze control’s place', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: { '/api/project-context': record(...ONE) },
    });
    await settle(page);
    expect(text('.next-cockpit-direction-said')).toBe(`Your ${clock(600)} message adds:`);
    expect(text('[data-next-cockpit-direction-whole]')).toContain('Do it the careful way');
    expect(
      [...document.querySelectorAll('.next-cockpit-reading-ask button')].map((b) => b.textContent),
    ).toEqual(['Add as a line', 'Make it the goal', 'Leave it', 'Analyze drift']);
    expect(page.posts('/api/annotate')).toBe(0);
  });

  it('asks nothing of a direction that was said before the words were saved, or already settled', async () => {
    const early = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: { '/api/project-context': record(fact('f0', 400, 'Said before saving')) },
    });
    await settle(early);
    expect(document.querySelector('[data-next-cockpit-direction-question]')).toBeNull();
    early.unmount();
    const settled = mountSession({
      store: { ...SAVED, settled_through: 600 },
      session: { ...SAVED_AT, annotation_settled_at: 800, annotation_settled_revision: 1 },
      routes: { '/api/project-context': record(...ONE) },
    });
    await settle(settled);
    expect(document.querySelector('[data-next-cockpit-direction-question]')).toBeNull();
    expect(text('.next-cockpit-conflict [data-slot=accordion-trigger]')).toMatch(
      /^Later directions: settled /,
    );
  });

  it('does not count a correction the reader copied from Compass as something they said', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(fact('f2', 650, 'A pasted correction', { copied: true })),
      },
    });
    await settle(page);
    expect(document.querySelector('[data-next-cockpit-direction-question]')).toBeNull();
  });

  it('names the selected direction of several and lets the reader pick another', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(
          fact('f1', 600, 'First one.'),
          fact('f2', 700, 'Second one.'),
        ),
      },
    });
    await settle(page);
    expect(text('.next-cockpit-direction-said')).toBe('2 later directions:');
    const pick = document.querySelector('[data-next-direction-select]') as HTMLButtonElement;
    await openSelect(pick);
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
      '#1 · First one.',
      '#2 · Second one.',
    ]);
    await chooseSelect(pick, 'f1');
    expect(text('.next-cockpit-direction-said')).toBe('2 later directions:');
    expect(pick.textContent).toContain('First');
    expect(page.posts('/api/annotate')).toBe(0);
  });

  it('says the record could not be read rather than saying there was no direction', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: { '/api/project-context': () => json({}, 500) },
    });
    await settle(page);
    expect(text('.next-cockpit-conflict [data-slot=accordion-trigger]')).toBe(
      'Later directions: unknown (record unread)',
    );
  });
});

describe('Add as a line', () => {
  it('reads the direction whole, opens it as one pending line that is not saved, and saves only on Save', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () =>
          json({ ok: true, text: 'Do it the careful way, with a flag', clipped: false }),
        '/api/annotate': () => stored(2),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    expect(presses(page).map((p) => p.path)).toEqual(['/api/direction']);
    expect(presses(page)[0]?.body).toEqual({ harness: 'claude', sid: 's1', fact_id: 'f1' });
    const line = document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement;
    expect(line.value).toBe('Do it the careful way, with a flag');
    expect(text('.next-cockpit-direction-line .next-cockpit-held-source')).toBe(
      `from your ${clock(600)} message · not saved`,
    );
    expect(document.activeElement).toBe(line);
    await press(control('held-save'));
    await settle(page);
    expect(presses(page)[1]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      add_direction: 'f1',
      text: 'Do it the careful way, with a flag',
      expected_revision: 1,
    });
    expect(document.querySelector('[data-next-cockpit-direction-key]')).toBeNull();
    // The saved line is said once in the polite region, as the legacy page says it.
    expect(text('#next-cockpit-cue-status')).toBe('Saved as a new revision.');
  });

  it('sends a second press to the line already pending and reads nothing again', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () => json({ ok: true, text: 'Original', clipped: false }),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    const line = document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement;
    type(line, 'My own edit');
    (document.activeElement as HTMLElement).blur();
    await press(control('direction-add'));
    expect(presses(page)).toHaveLength(1);
    expect(line.value).toBe('My own edit');
    expect(document.activeElement).toBe(line);
  });

  it('holds the whole text, counts it past the bound, and refuses to save it rather than cutting it', async () => {
    const long = 'w'.repeat(300);
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () => json({ ok: true, text: long, clipped: false }),
        '/api/annotate': () => stored(2),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    const line = document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement;
    expect(line.value).toHaveLength(300);
    expect(line.hasAttribute('maxlength')).toBe(false);
    expect(text('[data-next-cockpit-direction-count]')).toBe('300 / 240');
    expect(text('#next-cockpit-direction-why')).toBe(
      'A line holds 240 characters. Shorten this one to add it.',
    );
    expect(inert(control('held-save'))).toBe(true);
    await press(control('held-save'));
    expect(presses(page)).toHaveLength(1);
    type(line, 'short enough');
    expect(inert(control('held-save'))).toBe(false);
    expect(text('#next-cockpit-direction-why')).toBe('');
  });

  it('says a direction the server cannot open opens nothing, and tries again on the next press', async () => {
    let answers = 0;
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': (request) => {
          if (request.body?.['fact_ids']) return json({ results: [] });
          answers += 1;
          return answers === 1
            ? json({ ok: false, why: 'That entry is no longer in the record.' })
            : json({ ok: true, text: 'Opened now', clipped: false });
        },
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    expect(document.querySelector('[data-next-cockpit-direction-key]')).toBeNull();
    expect(document.body.textContent).toContain(
      'Compass could not open that direction. No outcome line was added.',
    );
    await press(control('direction-add'));
    await settle(page);
    expect(
      (document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement).value,
    ).toBe('Opened now');
  });

  it('keeps the line and says so when the store refuses the save', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () => json({ ok: true, text: 'Keep me', clipped: false }),
        '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    await press(control('held-save'));
    await settle(page);
    expect(
      (document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement).value,
    ).toBe('Keep me');
    expect(text('.next-cockpit-direction-line .next-cockpit-held-cue')).toBe(
      'Not saved. The server refused the write, and your words are still in the box.',
    );
  });

  it('saves an unsaved goal edit first and then the line, from the card’s one Save intent', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () => json({ ok: true, text: 'A line', clipped: false }),
        '/api/annotate': () => stored(2),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    type(goalBox(), 'Edited goal');
    // No "save first" refusal beside the line: the one Save intent carries both.
    expect(text('#next-cockpit-direction-why')).toBe('');
    expect(inert(control('held-save'))).toBe(false);
    await press(control('held-save'));
    await settle(page);
    const sent = presses(page).filter((p) => p.path === '/api/annotate');
    expect(sent[0]?.body).toMatchObject({ goal: 'Edited goal' });
    expect(sent[1]?.body).toMatchObject({ add_direction: 'f1', text: 'A line' });
  });

  it('names the line to replace when the list is full, counting from zero for the server', async () => {
    const page = mountSession({
      store: { ...SAVED, lines: ['1', '2', '3', '4', '5', '6'], revision: 2 },
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () =>
          json({ ok: true, text: 'Take the third line’s place', clipped: false }),
        '/api/annotate': () => stored(3),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    expect(text('#next-cockpit-direction-why')).toBe(
      'An expected outcome holds six lines. Replace or merge a line to add another.',
    );
    expect(inert(control('held-save'))).toBe(true);
    await press(control('direction-replace', '2'));
    expect(control('direction-replace', '2')?.getAttribute('aria-pressed')).toBe('true');
    expect(inert(control('held-save'))).toBe(false);
    await press(control('held-save'));
    await settle(page);
    expect(presses(page)[1]?.body).toMatchObject({
      add_direction: 'f1',
      replace: 2,
      expected_revision: 2,
    });
  });

  it('opens from an analysis result through the exported action, and sends one request to read it whole', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () => json({ ok: true, text: 'From the result card', clipped: false }),
      },
    });
    await settle(page);
    await act(async () => {
      await openPendingDirection(page.shell, { harness: 'claude', sid: 's1' }, 'f1');
    });
    await settle(page);
    expect(presses(page)).toHaveLength(1);
    expect(
      (document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement).value,
    ).toBe('From the result card');
    expect(text('.next-cockpit-direction-line .next-cockpit-held-source')).toBe(
      `from your ${clock(600)} message · not saved`,
    );
  });

  it('opens an empty line when there is no direction to offer', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: { '/api/project-context': record() },
    });
    await settle(page);
    await act(async () => {
      await openPendingDirection(page.shell, { harness: 'claude', sid: 's1' }, null);
    });
    expect(lineBoxes()).toHaveLength(2);
    expect(page.posts()).toBe(0);
  });
});

describe('Leave it', () => {
  it('a reader with twenty later directions on a week-long session sees them all in about the time of one', async () => {
    const facts = Array.from({ length: 20 }, (_, n) =>
      fact(`slow${String(n)}`, 600 + n, `Synthetic direction ${String(n)}.`),
    );
    const singleCost = 2000;
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...facts),
        '/api/direction': () => 'hold',
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    // One request reads all twenty, started by drawing the question and not by a press.
    expect(page.posts('/api/direction')).toBe(1);
    expect(page.allPosts()[0]?.body?.['fact_ids']).toHaveLength(20);
    await page.advance(singleCost);
    await page.release(
      '/api/direction',
      json({
        results: facts.map((f) => ({
          ok: true,
          text: `${f.summary} Complete words.`,
          clipped: false,
        })),
      }),
    );
    await settle(page);
    expect(document.querySelectorAll('.next-cockpit-direction-whole-item')).toHaveLength(20);
    expect(text('.next-cockpit-direction-whole')).toContain(
      'Synthetic direction 19. Complete words.',
    );
    expect(page.posts('/api/annotate')).toBe(0);
    await press(control('direction-keep'));
    await settle(page);
    expect(page.posts('/api/annotate')).toBe(1);
    expect(text('#next-cockpit-cue-status')).toBe(
      'Kept your intent and settled all 20 directions. No analysis was started.',
    );
  });

  it('settles what the reader was shown on the first press, and asks again for what arrived unread', async () => {
    let retry = false;
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(
          fact('f1', 600, 'First.'),
          fact('f2', 700, 'Second.'),
          fact('f3', 800, 'Third.'),
        ),
        '/api/direction': () =>
          json({
            results: retry
              ? [
                  { ok: true, text: 'Second complete.', clipped: false },
                  { ok: true, text: 'Third complete.', clipped: false },
                ]
              : [
                  { ok: true, text: 'First complete.', clipped: false },
                  { ok: false, reason: 'out_of_reach' },
                  { ok: false, reason: 'not_found' },
                ],
          }),
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    // The partial read quotes what it could open, and Leave it refuses to settle words it could not show.
    expect(text('.next-cockpit-direction-whole')).toContain('First complete.');
    await press(control('direction-keep'));
    await settle(page);
    expect(text('.next-cockpit-direction-question')).toContain(
      'Nothing was settled and no analysis was started',
    );
    expect(page.posts('/api/annotate')).toBe(0);
    retry = true;
    await press(control('direction-keep'));
    await settle(page);
    expect(page.allPosts().at(-1)?.body?.['fact_ids']).toEqual(['f2', 'f3']);
    expect(document.querySelectorAll('.next-cockpit-direction-whole-item')).toHaveLength(3);
    // Words the press just drew were not on screen when it was made, so they are read first.
    expect(page.posts('/api/annotate')).toBe(0);
    await press(control('direction-keep'));
    await settle(page);
    expect(page.posts('/api/annotate')).toBe(1);
  });

  it('tells a reader how many of their several later directions were settled', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(
          fact('f1', 600, 'First direction.'),
          fact('f2', 700, 'Second direction.'),
        ),
        '/api/direction': () =>
          json({
            results: [
              { ok: true, text: 'Synthetic direction.', clipped: false },
              { ok: true, text: 'Another synthetic direction.', clipped: false },
            ],
          }),
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    expect(text('.next-cockpit-direction-question')).toContain(
      'Kept your intent and settled all 2 directions. No analysis was started.',
    );
  });

  const WHOLE_WORDS = 'Do it the careful way, and then verify it on a clean checkout.';
  const oneDirection = {
    '/api/project-context': record(fact('f1', 600, 'Do it the careful way, and then verify it')),
    '/api/direction': () =>
      json({
        results: [{ ok: true, text: WHOLE_WORDS, clipped: false }],
        ok: true,
        text: WHOLE_WORDS,
        clipped: false,
      }),
    '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
  };

  it('quotes the whole direction before any press and settles on the first, naming the revision it drew', async () => {
    const page = mountSession({ store: SAVED, session: SAVED_AT, routes: oneDirection });
    await settle(page);
    // The summary quoted only its first words; the whole text is already drawn, so nothing waits on a second press.
    expect(text('.next-cockpit-direction-whole')).toContain(WHOLE_WORDS);
    expect(page.allPosts().map((p) => p.path)).toEqual(['/api/direction']);
    await press(control('direction-keep'));
    await settle(page);
    expect(page.allPosts().map((p) => p.path)).toEqual(['/api/direction', '/api/annotate']);
    expect(page.allPosts()[1]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      settle_through: 600,
      expected_revision: 1,
    });
    expect(text('.next-cockpit-direction-question')).toContain(
      'Kept your intent and settled the direction. No analysis was started.',
    );
  });

  it('refuses over an unsaved edit with the one sentence, settling nothing', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: { '/api/project-context': record(...ONE) },
    });
    await settle(page);
    type(goalBox(), 'Edited goal');
    await press(control('direction-keep'));
    expect(presses(page)).toEqual([]);
    expect(text('#next-cockpit-cue-status')).toBe(
      'Save your intent, or undo your edit, to analyze drift.',
    );
  });

  it('says nothing was settled when a direction cannot be opened, and reads again before it settles', async () => {
    let first = true;
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () =>
          first
            ? json({ ok: false })
            : json({
                results: [{ ok: true, text: 'Do it the careful way', clipped: false }],
              }),
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    expect(text('.next-cockpit-direction-question')).toContain(
      'Compass could not open that direction. Nothing was settled and no analysis was started.',
    );
    expect(presses(page).filter((p) => p.path === '/api/annotate')).toHaveLength(0);
    first = false;
    await press(control('direction-keep'));
    await settle(page);
    // Read now, so drawn only now: it is shown before it is settled.
    expect(presses(page).filter((p) => p.path === '/api/annotate')).toHaveLength(0);
    await press(control('direction-keep'));
    await settle(page);
    expect(presses(page).filter((p) => p.path === '/api/annotate')).toHaveLength(1);
  });

  it('names the revision it drew, so words saved since are refused rather than settled over', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        ...oneDirection,
        '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }),
      },
    });
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    expect(page.allPosts()[1]?.body).toMatchObject({ expected_revision: 1, settle_through: 600 });
    expect(text('.next-cockpit-direction-question')).toContain(
      'Nothing was settled and no analysis was started: your intent changed since this page was drawn, or the store refused the mark.',
    );
    // A refused Leave it keeps the words it drew, so the next press acts on what is still on screen.
    expect(text('[data-next-cockpit-direction-whole]')).toContain('verify it on a clean');
  });
});

describe('Use this as my goal', () => {
  it('fills the goal box with the direction and asks whether to keep the standing outcome lines', async () => {
    const page = mountSession({
      store: { ...SAVED, lines: ['A standing line'], revision: 2 },
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () =>
          json({
            ok: true,
            goal_choice: { fact_id: 'f1', text: 'Do it the careful way', at: 600, cut: false },
          }),
        '/api/annotate': () => stored(3),
      },
    });
    await settle(page);
    await press(control('direction-goal'));
    await settle(page);
    expect(goalBox().value).toBe('Do it the careful way');
    expect(presses(page)).toHaveLength(1);
    expect(inert(control('held-save'))).toBe(true);
    expect(text('.next-cockpit-held-field[data-next-cockpit-held-field="goal"]')).toContain(
      'Keep your standing outcome lines with this goal?',
    );
    await press(control('direction-lines-clear'));
    expect(lineBoxes().map((b) => b.value)).toEqual(['']);
    expect(inert(control('held-save'))).toBe(false);
  });
});

describe('a direction press that cannot finish', () => {
  it('clears a line-level goal refusal when the reader edits their pending outcome', async () => {
    let opened = false;
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': (request) => {
          if (request.body?.['fact_ids']) return json({ results: [] });
          if (opened) return json({ ok: false, reason: 'out_of_reach' });
          opened = true;
          return json({ ok: true, text: 'A synthetic pending outcome', clipped: true });
        },
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    const line = document.querySelector('[data-next-cockpit-direction-line]') as HTMLElement;
    const goal = line.querySelector(
      '[data-next-cockpit-action="direction-goal"]',
    ) as HTMLButtonElement;
    await press(goal);
    await settle(page);
    expect(goal.parentElement?.querySelector('[data-next-action-feedback]')).not.toBeNull();
    type(line.querySelector('textarea') as HTMLTextAreaElement, 'My own reviewed line');
    await settle(page);
    expect(goal.parentElement?.querySelector('[data-next-action-feedback]')).toBeNull();
  });
  it('tells a reader at the activity row when its direction is beyond the search and retains that row focus', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () => json({ ok: false, reason: 'out_of_reach' }),
      },
    });
    await settle(page);
    const row = document.querySelector('[data-next-entry-id="f1"]') as HTMLElement;
    const button = row.querySelector(
      'button[data-next-cockpit-action="direction-add"]',
    ) as HTMLButtonElement;
    button.focus();
    await press(button);
    await settle(page);
    const message =
      'That direction is beyond the part of the record Compass could search. No outcome line was added.';
    expect(button.parentElement?.querySelector('[data-next-action-feedback]')?.textContent).toBe(
      message,
    );
    expect(document.querySelector('#next-cockpit-cue-status')?.textContent).toBe(message);
    expect(document.activeElement).toBe(button);
  });

  it('keeps a complete settlement refusal beside Keep until the reader edits their intent', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(...ONE),
        '/api/direction': () =>
          json({ results: [{ ok: true, text: 'Synthetic later direction', clipped: false }] }),
        '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }),
      },
    });
    await settle(page);
    const button = control('direction-keep') as HTMLButtonElement;
    button.focus();
    await press(button);
    await settle(page);
    const message = button.parentElement?.querySelector('[data-next-action-feedback]');
    expect(message?.textContent).toMatch(
      /Nothing was settled.*Review your intent and press again\.$/,
    );
    expect(document.querySelector('#next-cockpit-cue-status')?.textContent).toBe(
      message?.textContent,
    );
    expect(document.activeElement).toBe(button);
    type(goalBox(), 'An edited goal');
    await settle(page);
    expect(button.parentElement?.querySelector('[data-next-action-feedback]')).toBeNull();
  });

  for (const [reason, explanation] of [
    [
      'not_found',
      'That direction could not be verified as later than your intent in the current record.',
    ],
    ['out_of_reach', 'That direction is beyond the part of the record Compass could search.'],
    ['changed', 'The session wrote to its record while Compass was reading it. Press again.'],
  ] as const) {
    for (const [action, ending] of [
      ['direction-goal', 'Your goal has not changed.'],
      ['direction-add', 'No outcome line was added.'],
      ['direction-keep', 'Nothing was settled and no analysis was started.'],
    ] as const) {
      it(`tells a reader at ${action} why ${reason} changed nothing and keeps their focus`, async () => {
        const page = mountSession({
          store: SAVED,
          session: SAVED_AT,
          routes: {
            '/api/project-context': record(...ONE),
            '/api/direction': () => json({ ok: false, reason, why: 'Server source explanation.' }),
          },
        });
        await settle(page);
        const button = control(action) as HTMLButtonElement;
        button.focus();
        await press(button);
        await settle(page);
        const message = `${explanation} ${ending}`;
        expect(
          button.parentElement?.querySelector('[data-next-action-feedback]')?.textContent,
        ).toBe(message);
        expect(document.querySelector('#next-cockpit-cue-status')?.textContent).toBe(message);
        expect(document.querySelector('#next-cockpit-cue-status')?.getAttribute('aria-live')).toBe(
          'polite',
        );
        expect(document.activeElement).toBe(button);
        expect(goalBox().value).toBe(SAVED.goal);
        expect(document.querySelector('[data-next-cockpit-direction-key]')).toBeNull();
        await page.poll(board(SAVED_AT, SAVED));
        await settle(page);
        expect(
          button.parentElement?.querySelector('[data-next-action-feedback]')?.textContent,
        ).toBe(message);
      });
    }
  }
});

/* Claude Code wraps a paste as `<pasted_content id="N">` and `</pasted_content>` around the pasted words. A
   server that predates the strip, or a direction history republished from before it, still sends them, and
   the quote, the pending line and a goal the direction became must never show the tags. */
const WRAPPED =
  '\n\n<pasted_content id="3">\nBack to my goal: Ship the worker\n</pasted_content>\n';
const UNWRAPPED = 'Back to my goal: Ship the worker';

describe('a harness paste wrapper around a direction', () => {
  it('is never drawn in the whole direction Keep shows before it settles', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(fact('f1', 600, 'Back to my goal')),
        '/api/direction': () => json({ ok: true, text: WRAPPED, clipped: false }),
        '/api/annotate': () => stored(1, { outcome: 'unchanged' }),
      },
    });
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    expect(text('[data-next-cockpit-direction-whole]')).toContain(UNWRAPPED);
    expect(text('[data-next-cockpit-direction-whole]')).not.toContain('pasted_content');
  });

  it('is never put in the pending line Add opens', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(fact('f1', 600, 'Back to my goal')),
        '/api/direction': () => json({ ok: true, text: WRAPPED, clipped: false }),
      },
    });
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    const line = document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement;
    expect(line.value).toBe(UNWRAPPED);
  });

  it('is never drawn in the quoted summary beside the question', async () => {
    const page = mountSession({
      store: SAVED,
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(
          fact('f1', 600, '<pasted_content id="3"> Back to my goal: Ship the worker'),
          fact('f2', 610, 'Do it the careful way'),
        ),
      },
    });
    await settle(page);
    expect(text('.next-cockpit-direction-question')).not.toContain('pasted_content');
  });
});
