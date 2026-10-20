import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { RecordedRequest } from '../intent/testing';
import { byAction, check, driftBoard, fact, json, mountDrift, press, textOf } from './testing';

const ASSESSMENT = {
  revision_read: 3,
  revision_read_at: 990,
  window_start: 100,
  read_at: 1000,
  evidence_through: 1000,
  goal_source: 'typed',
  scope: 'last-turn',
  criteria: {
    goal: { result: 'departure', cites: ['c1'], detail: 'It stopped.', clause: 'Ship the queue' },
  },
};
const FACTS = [check('c1', 500, 'failed', { result_source: 'failed flag' })];
const session = { annotation_assessment: ASSESSMENT, annotation_window_start: 100 };
const PARTS = ['Your last check failed', { entry: 'c1' }, '. Fix it, then say so.'];
const corrections = (page: { state: { requests: RecordedRequest[] } }) =>
  page.state.requests.filter((r) => r.method === 'POST' && r.path.startsWith('/api/correction'));
const box = () => document.querySelector<HTMLTextAreaElement>('#next-cockpit-correction');

function mountSteer(extra: Record<string, unknown> = {}) {
  return mountDrift({
    session,
    facts: FACTS,
    routes: {
      '/api/correction': () => json({ ok: true, parts: PARTS }),
      '/api/correction/copied': () => json({ ok: true }),
    },
    ...extra,
  });
}

describe('Steer back', () => {
  it('tells a reader beside Update intent when its offered direction cannot be opened', async () => {
    const page = mountSteer({
      facts: [...FACTS, fact('d1', 995)],
      store: { settled_through: 995 },
      session: { ...session, annotation_settled_at: 1000, annotation_settled_revision: 3 },
      routes: { '/api/direction': () => json({ ok: false, reason: 'out_of_reach' }) },
    });
    await page.settle();
    await page.settle();
    const button = byAction('update-intent') as HTMLButtonElement;
    expect(button).not.toBeNull();
    button.focus();
    await press(button);
    await page.settle();
    expect(button.parentElement?.querySelector('[data-next-action-feedback]')?.textContent).toBe(
      'That direction is beyond the part of the record Compass could search. No outcome line was added.',
    );
    expect(document.activeElement).toBe(button);
  });
  it('composes nothing until pressed, then once, and writes nothing into the session', async () => {
    const page = mountSteer({ strict: true });
    await page.settle();
    await page.settle();
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(corrections(page)).toEqual([]);
    expect(byAction('steer-back')?.getAttribute('aria-expanded')).toBe('false');
    await press(byAction('steer-back'));
    await page.settle();
    expect(corrections(page)).toHaveLength(1);
    expect(corrections(page)[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      utc_offset_minutes: 0 - new Date().getTimezoneOffset() || 0,
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    expect(box()?.value).toBe('Your last check failed. Fix it, then say so.');
    expect(byAction('steer-back')?.getAttribute('aria-expanded')).toBe('true');
    expect(textOf('[data-next-steer-box]')).toContain('Compass never sends this.');
    // Every request so far was a read or the one composition: nothing reached the session.
    expect(page.state.requests.filter((r) => r.method !== 'GET')).toHaveLength(1);
  });

  it("closes on a second press and keeps the reader's edit across the close", async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.value = 'My own words.';
    await act(async () => {
      fireEvent.input(field);
    });
    await press(byAction('steer-back'));
    expect(box()).toBeNull();
    await press(byAction('steer-back'));
    expect(box()?.value).toBe('My own words.');
    expect(corrections(page)).toHaveLength(1);
  });

  it('counts code points as the server does and refuses a paste over the cap, keeping the text', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.value = '😀'.repeat(1000);
    await act(async () => {
      fireEvent.input(field);
    });
    expect(textOf('[data-next-correction-count]')).toBe('1000/5140');
    const before = field.value;
    field.value = `${before}${'x'.repeat(4500)}`;
    await act(async () => {
      fireEvent.input(field);
    });
    expect(field.value).toBe(before);
    expect(textOf('[data-next-correction-edit-why]')).toContain('This edit is unavailable here.');
  });

  it('copies the exact text, records it once, and says Copied until an accepted edit', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    await press(byAction('correction-copy'));
    await page.settle();
    expect(page.written).toEqual(['Your last check failed. Fix it, then say so.']);
    const recorded = corrections(page).filter((r) => r.path === '/api/correction/copied');
    expect(recorded).toHaveLength(1);
    expect(recorded[0]?.body).toEqual({
      harness: 'claude',
      sid: 's1',
      text: 'Your last check failed. Fix it, then say so.',
    });
    expect(textOf('[data-next-correction-cue]')).toBe('Copied');
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    expect(textOf('[data-next-correction-cue]')).toBe('Copied');
    const field = box() as HTMLTextAreaElement;
    field.value = `${field.value} More.`;
    await act(async () => {
      fireEvent.input(field);
    });
    expect(textOf('[data-next-correction-cue]')).toBe('Copy');
  });

  it('writes one copy for one press however it is pressed', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const copy = byAction('correction-copy') as HTMLElement;
    await act(async () => {
      fireEvent.click(copy);
      fireEvent.click(copy);
      fireEvent.click(copy);
    });
    await page.settle();
    expect(page.written).toHaveLength(1);
    expect(corrections(page).filter((r) => r.path === '/api/correction/copied')).toHaveLength(1);
  });

  it('waits to show a board that arrives while the reader is editing, and shows it on leaving', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.focus();
    field.value = 'Half a thought';
    await act(async () => {
      fireEvent.input(field);
    });
    const running = {
      ...driftBoard({ session }),
      generated: 1300,
      reading_jobs: {
        'claude:s1': { id: 'j1', phase: 'read', steps: [{ phase: 'read', text: 'Reading' }] },
      },
    };
    await page.poll(running);
    // The board with a running analysis is accepted, but the card the reader is typing under is not redrawn.
    expect(document.querySelector('[data-next-analyzing]')).toBeNull();
    expect(box()).toBe(field);
    await act(async () => {
      field.blur();
    });
    await page.settle();
    expect(document.querySelector('[data-next-analyzing="j1"]')).not.toBeNull();
  });

  it('waits through a pointer on its way to a control, and shows the board once the click lands', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.focus();
    field.value = 'Half a thought';
    await act(async () => {
      fireEvent.input(field);
    });
    const copy = byAction('correction-copy') as HTMLElement;
    await act(async () => {
      fireEvent.pointerDown(copy, { button: 0, pointerId: 4, isPrimary: true });
      // The browser blurs the box between the press and the click.
      field.blur();
    });
    const running = {
      ...driftBoard({ session }),
      generated: 1300,
      reading_jobs: {
        'claude:s1': { id: 'j1', phase: 'read', steps: [{ phase: 'read', text: 'Reading' }] },
      },
    };
    await page.poll(running);
    expect(document.querySelector('[data-next-analyzing]')).toBeNull();
    await act(async () => {
      fireEvent.click(copy);
    });
    await page.advance(5);
    await page.settle();
    expect(document.querySelector('[data-next-analyzing="j1"]')).not.toBeNull();
    // The press that was waited for was not swallowed.
    expect(page.written).toHaveLength(1);
  });

  it('keeps the same editor node, and the words in it, across a board that arrives while it is edited', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.focus();
    field.value = 'Half a thought';
    await act(async () => {
      fireEvent.input(field);
    });
    field.setSelectionRange(4, 4);
    // New work lands: the reading is now stale, which would move the box in the tree.
    await page.poll({
      ...driftBoard({ session }),
      generated: 1300,
    });
    page.state.data = driftBoard({ session });
    expect(box()).toBe(field);
    expect(field.value).toBe('Half a thought');
    expect(document.activeElement).toBe(field);
    expect(field.selectionStart).toBe(4);
    expect(textOf('[data-next-correction-paint-why]')).toBe(
      'Updates are paused while you edit this correction. Leave the box to show new work.',
    );
    await act(async () => {
      field.blur();
    });
    expect(textOf('[data-next-correction-paint-why]')).toBe('');
  });
});

describe('Steer back beside a question', () => {
  it('is not offered while a later direction is unsettled: the question owns that slot', async () => {
    const page = mountSteer({
      facts: [
        ...FACTS,
        { ...check('d1', 995, ''), type: 'user_message', subject: '', by: 'person:me' },
      ],
      session: { ...session, annotation_goal_saved_at: 500, annotation_at: 500 },
    });
    await page.settle();
    await page.settle();
    expect(document.querySelector('[data-next-cockpit-direction-question]')).not.toBeNull();
    expect(byAction('steer-back')).toBeNull();
  });
});

/* The correction composes again for the record as it stands only where the reader opened the box, left it
   unedited, and the record then changed: one deterministic server read, never a model call, once per change
   and never for a box that is closed. */
describe('a correction the reader opened follows the record, honestly', () => {
  const newWork = [...FACTS, check('c9', 1200, 'passed')];
  /* Opens the box and leaves it, as a reader does; the card shows boards again from then on. */
  async function openAndLeave(page: ReturnType<typeof mountSteer>) {
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    await act(async () => {
      field.blur();
    });
    return field;
  }

  it('composes once more for one change in the record, however many boards follow', async () => {
    const page = mountSteer({
      strict: true,
      routes: {
        '/api/correction': () => json({ ok: true, parts: PARTS }),
        '/api/project-context': () => json({ semantic: { facts: newWork } }),
      },
    });
    await page.settle();
    await page.settle();
    await openAndLeave(page);
    expect(corrections(page)).toHaveLength(1);
    // The reading moves on (its read time is part of what the correction was composed from).
    const moved = { ...ASSESSMENT, read_at: 1100 };
    for (const generated of [1300, 1400, 1500]) {
      await page.poll({
        ...driftBoard({ session: { ...session, annotation_assessment: moved } }),
        generated,
      });
    }
    await page.settle();
    expect(corrections(page).filter((r) => r.path === '/api/correction')).toHaveLength(2);
    await page.advance(60_000);
    await page.poll({
      ...driftBoard({ session: { ...session, annotation_assessment: moved } }),
      generated: 1600,
    });
    expect(corrections(page).filter((r) => r.path === '/api/correction')).toHaveLength(2);
  });

  it('asks once while the recomposition is out, however many boards arrive meanwhile', async () => {
    let calls = 0;
    const page = mountSteer({
      routes: {
        '/api/correction': () => {
          calls += 1;
          return calls === 1 ? json({ ok: true, parts: PARTS }) : 'hold';
        },
      },
    });
    await page.settle();
    await page.settle();
    await openAndLeave(page);
    const moved = { ...ASSESSMENT, read_at: 1100 };
    for (const generated of [1300, 1400, 1500, 1600]) {
      await page.poll({
        ...driftBoard({ session: { ...session, annotation_assessment: moved } }),
        generated,
      });
    }
    expect(corrections(page).filter((r) => r.path === '/api/correction')).toHaveLength(2);
  });

  it('never composes for a box the reader closed', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await openAndLeave(page);
    await press(byAction('steer-back'));
    expect(box()).toBeNull();
    const moved = { ...ASSESSMENT, read_at: 1100 };
    for (const generated of [1300, 1400]) {
      await page.poll({
        ...driftBoard({ session: { ...session, annotation_assessment: moved } }),
        generated,
      });
    }
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(corrections(page).filter((r) => r.path === '/api/correction')).toHaveLength(1);
  });

  it('leaves an edited box alone, says it is from an older record, and recomposes once per press', async () => {
    const page = mountSteer({
      routes: {
        '/api/correction': () => json({ ok: true, parts: PARTS }),
      },
    });
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.value = 'Mine.';
    await act(async () => {
      fireEvent.input(field);
      field.blur();
    });
    const moved = { ...ASSESSMENT, read_at: 1100 };
    await page.poll({
      ...driftBoard({ session: { ...session, annotation_assessment: moved } }),
      generated: 1300,
    });
    expect(corrections(page).filter((r) => r.path === '/api/correction')).toHaveLength(1);
    expect(document.querySelector('[data-next-correction-older]')).not.toBeNull();
    const recompose = byAction('correction-recompose') as HTMLElement;
    await act(async () => {
      fireEvent.click(recompose);
      fireEvent.click(recompose);
      fireEvent.click(recompose);
    });
    await page.settle();
    expect(corrections(page).filter((r) => r.path === '/api/correction')).toHaveLength(2);
  });
});

describe('a focused correction box keeps its node, caret and selection when the layout shifts', () => {
  it('holds the card while the reader is in an untouched box', async () => {
    const page = mountSteer();
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.settle();
    const field = box() as HTMLTextAreaElement;
    field.focus();
    field.setSelectionRange(2, 7);
    // New work lands: a stale mark that would move the box in the tree.
    await page.poll({ ...driftBoard({ session }), generated: 1300 });
    page.state.data = driftBoard({ session });
    expect(box()).toBe(field);
    expect([field.selectionStart, field.selectionEnd]).toEqual([2, 7]);
    expect(document.activeElement).toBe(field);
  });
});

describe('a compose answer arriving after the reader left asks for nothing', () => {
  it('does not move focus into the box on return', async () => {
    const page = mountSteer({
      routes: {
        '/api/correction': () => 'hold',
        '/api/correction/copied': () => json({ ok: true }),
      },
    });
    await page.settle();
    await page.settle();
    await press(byAction('steer-back'));
    await page.go('#n=intent');
    await page.release('/api/correction', json({ ok: true, parts: PARTS }));
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.settle();
    expect(box()).not.toBeNull();
    expect(document.activeElement).not.toBe(box());
  });
});
