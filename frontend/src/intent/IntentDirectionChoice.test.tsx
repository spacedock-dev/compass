import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { clock } from '../observed';
import { trimToRule } from './annotation';
import { json } from './testing';
import { control, goalBox, inert, mountSession, stored, text } from './panel.testing';

/* A later direction is quoted, with its time, where the reader chooses what to do with it, and each choice
   acts on its first press. Add as a line and Make it the goal start from the rule in the message rather than
   the whole message, say so, and are saved by the card's one Save intent. */

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null) => {
  await act(async () => {
    fireEvent.click(button as Element);
  });
};

const fact = (id: string, at: number, summary: string) => ({
  fact_id: id,
  type: 'user_message',
  by: 'person:me',
  summary,
  at,
  source_session: { harness: 'claude', sid: 's1' },
});
const record =
  (...facts: unknown[]) =>
  () =>
    json({ semantic: { facts } });

const SAVED = { goal: 'Ship the worker', revision: 1 };
const SAVED_AT = { annotation_goal_saved_at: 500, annotation_at: 500 };
const WHOLE = 'Keep the flag off by default. Then run the targeted tests, and push.';
const RULE = 'Keep the flag off by default.';
const HINT = 'Write the rule, not the moment.';

function mount(extra: Record<string, unknown> = {}) {
  return mountSession({
    store: SAVED,
    session: SAVED_AT,
    routes: {
      '/api/project-context': record(fact('f1', 600, 'Keep the flag off by default.')),
      '/api/direction': (request: unknown) => {
        const body = (request as { body?: { fact_ids?: string[] } })?.body;
        void body;
        return json({
          ok: true,
          text: WHOLE,
          clipped: false,
          results: [{ ok: true, text: WHOLE, clipped: false }],
          goal_choice: { fact_id: 'f1', text: WHOLE, at: 600, cut: false },
        });
      },
      '/api/annotate': () => stored(2),
      ...extra,
    },
  });
}

describe('a later direction is quoted where it is settled', () => {
  it('quotes the whole message under its time before any press, beside the three choices', async () => {
    const page = mount();
    await settle(page);
    expect(text('.next-cockpit-direction-said')).toContain(`Your ${clock(600)} message adds:`);
    expect(text('[data-next-cockpit-direction-whole]')).toContain(WHOLE);
    expect(
      [...document.querySelectorAll('.next-cockpit-reading-ask button')].map((b) => b.textContent),
    ).toEqual(['Add as a line', 'Make it the goal', 'Leave it', 'Analyze drift']);
  });

  it('settles on the first press of Leave it, with the words already on screen', async () => {
    const page = mount({ '/api/annotate': () => stored(1, { outcome: 'unchanged' }) });
    await settle(page);
    await press(control('direction-keep'));
    await settle(page);
    expect(page.allPosts().map((p) => p.path)).toEqual(['/api/direction', '/api/annotate']);
    expect(page.allPosts()[1]?.body).toMatchObject({ settle_through: 600, expected_revision: 1 });
  });
});

describe('Add as a line', () => {
  it('opens the rule with its hint on the first press and is saved by the one Save intent', async () => {
    const page = mount();
    await settle(page);
    await press(control('direction-add'));
    await settle(page);
    const line = document.querySelector('[data-next-cockpit-direction-key]') as HTMLTextAreaElement;
    expect(line.value).toBe(RULE);
    expect(text('.next-cockpit-direction-line')).toContain(HINT);
    expect(text('.next-cockpit-direction-line .next-cockpit-held-source')).toBe(
      `from your ${clock(600)} message · not saved`,
    );
    const saves = [...document.querySelectorAll('button')].filter((b) =>
      /^save\b/i.test(b.textContent ?? ''),
    );
    expect(saves.map((b) => b.textContent)).toEqual(['Save intent']);
    expect(inert(control('held-save'))).toBe(false);
    await press(control('held-save'));
    await settle(page);
    expect(page.allPosts().at(-1)?.body).toMatchObject({
      add_direction: 'f1',
      text: RULE,
      expected_revision: 1,
    });
    expect(document.querySelector('[data-next-cockpit-direction-key]')).toBeNull();
  });
});

describe('Make it the goal', () => {
  it('fills the goal with the rule and its hint on the first press, saved by the one Save intent', async () => {
    const page = mount();
    await settle(page);
    await press(control('direction-goal'));
    await settle(page);
    expect(goalBox().value).toBe(RULE);
    expect(text('[data-next-cockpit-held-field="goal"]')).toContain(HINT);
    const saves = [...document.querySelectorAll('button')].filter((b) =>
      /^save\b/i.test(b.textContent ?? ''),
    );
    expect(saves.map((b) => b.textContent)).toEqual(['Save intent']);
  });
});

describe('the rule in a direction', () => {
  it('is its first sentence, and a message with no sentence break is its own rule', () => {
    expect(trimToRule(WHOLE)).toBe(RULE);
    expect(trimToRule('Do it the careful way, with a flag')).toBe(
      'Do it the careful way, with a flag',
    );
    expect(trimToRule('\n\nFirst line without a stop\nSecond line. Third.')).toBe(
      'First line without a stop',
    );
    expect(trimToRule('Ship v1.2 first. Then more.')).toBe('Ship v1.2 first.');
    expect(trimToRule('')).toBe('');
  });
});

describe('keeping the standing outcome lines', () => {
  it('asks with two buttons beside the question after a direction becomes the goal', async () => {
    const page = mountSession({
      store: { ...SAVED, lines: ['A standing line'], revision: 2 },
      session: SAVED_AT,
      routes: {
        '/api/project-context': record(fact('f1', 600, 'Keep the flag off by default.')),
        '/api/direction': () =>
          json({
            ok: true,
            results: [{ ok: true, text: WHOLE, clipped: false }],
            goal_choice: { fact_id: 'f1', text: WHOLE, at: 600, cut: false },
          }),
      },
    });
    await settle(page);
    await press(control('direction-goal'));
    await settle(page);
    const asked = document.querySelector('[data-next-direction-lines-question]') as HTMLElement;
    expect(asked.textContent).toContain('Keep your standing outcome lines with this goal?');
    const buttons = [...asked.querySelectorAll('button')];
    expect(buttons.map((b) => b.textContent)).toEqual([
      'Keep outcome lines',
      'Clear outcome lines',
    ]);
    for (const button of buttons) expect(button.getAttribute('data-variant')).not.toBe('ghost');
  });
});
