import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json } from './testing';
import { board, control, goalBox, mountSession, text, type } from './panel.testing';

/* Discard everything: one act over two stores, armed by the first press and performed by the second, with
   every sentence the server's. A double-click, a held key and a slip are all one press, never two. */

const SENTENCES = {
  why: 'This deletes every revision and the stored reading.',
  armed: 'Nothing has been deleted yet. Press again to delete every revision.',
  stored: 'Discarded. These words are gone.',
  refused: 'Nothing was discarded: the store refused.',
  unwritable: 'The discard could not be written.',
  stored_no_summary: 'Discarded. There was no stored summary.',
  summary_kept: 'Discarded, but the summary is still stored. Delete summary removes it.',
  summary_unavailable: 'Discarded. The summary store could not be read.',
  nothing: 'Nothing to discard.',
  record: 'You discarded these words.',
};
const withSentences = (data: object) => ({ ...data, annotate_discard: SENTENCES });

const settle = async (page: { settle: () => Promise<void> }) => {
  await page.settle();
  await page.settle();
};
const press = async (button: Element | null, detail = 1) => {
  await act(async () => {
    fireEvent.click(button as Element, { detail });
  });
};
const discard = () => control('held-discard');

function mount(
  routes: Parameters<typeof mountSession>[0] extends infer O
    ? O extends { routes?: infer R }
      ? R
      : never
    : never = {},
) {
  return mountSession({
    store: { goal: 'Saved goal', revision: 2 },
    routes,
  });
}

async function armed(page: ReturnType<typeof mount>) {
  page.state.data = withSentences(page.state.data as object);
  await page.poll(page.state.data);
  await press(discard());
}

describe('Discard everything', () => {
  it('is offered only over words that exist, behind its own summary', async () => {
    const page = mountSession();
    await settle(page);
    expect(discard()).toBeNull();
    page.unmount();
    const saved = mount();
    await settle(saved);
    expect(text('.next-cockpit-held-discard-offer [data-slot=accordion-trigger]')).toBe(
      'Discard everything',
    );
    expect(discard()?.textContent).toBe('Discard everything');
  });

  it('arms on the first press, sends nothing, warns assertively and describes the armed control by the warning', async () => {
    const page = mount({
      '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true }),
    });
    await settle(page);
    await armed(page);
    expect(page.posts()).toBe(0);
    expect(discard()?.textContent).toBe('Confirm discard');
    expect(text('#next-cockpit-cue-alert')).toBe(SENTENCES.armed);
    expect(discard()?.getAttribute('aria-describedby')).toBe('next-cockpit-discard-armed');
    expect(text('#next-cockpit-discard-armed')).toBe(SENTENCES.armed);
    expect(
      document.querySelector('.next-cockpit-held-discard-offer')?.hasAttribute('data-open'),
    ).toBe(true);
  });

  it('treats a press inside the dwell, and a double-click, as another arm and never as a confirmation', async () => {
    const page = mount({
      '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true }),
    });
    await settle(page);
    await armed(page);
    await act(async () => {
      page.clock.advance(1_000);
    });
    await press(discard());
    expect(page.posts()).toBe(0);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard(), 2);
    expect(page.posts()).toBe(0);
    expect(discard()?.textContent).toBe('Confirm discard');
  });

  it('performs on the second press after the dwell, naming the exact session, once', async () => {
    const page = mount({
      '/api/annotate': () => {
        page.state.data = withSentences(board({}, { discarded: true }));
        return json({ ok: true, outcome: 'stored', persisted: true, withdrew: true });
      },
    });
    await settle(page);
    await armed(page);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    expect(page.allPosts()).toHaveLength(1);
    expect(page.allPosts()[0]?.body).toEqual({ harness: 'claude', sid: 's1', clear: true });
    expect(text('.next-cockpit-held-discard .next-cockpit-held-cue')).toBe(SENTENCES.stored);
    expect(text('#next-cockpit-cue-status')).toBe(SENTENCES.stored);
    // The alert region no longer holds a warning that says nothing was deleted.
    expect(text('#next-cockpit-cue-alert')).toBe('');
  });

  it('drops the drafts with the annotation, so the next save does not mint revision 1 of discarded words', async () => {
    const page = mount({
      '/api/annotate': () => {
        page.state.data = withSentences(board({}, { discarded: true }));
        return json({ ok: true, outcome: 'stored', persisted: true, withdrew: true });
      },
    });
    await settle(page);
    type(goalBox(), 'half-typed words');
    page.state.data = withSentences(page.state.data as object);
    await page.poll(page.state.data);
    await press(discard());
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    expect(goalBox().value).not.toBe('half-typed words');
  });

  it('starts the form empty after a discard, and never refills it from the drafted prompt', async () => {
    const DISCARDED = { annotation_discarded_at: 1000, annotation_revision_count: 0 };
    const page = mount({
      '/api/annotate': () => {
        page.state.data = withSentences(board(DISCARDED));
        return json({ ok: true, outcome: 'stored', persisted: true, withdrew: true });
      },
    });
    await settle(page);
    expect(goalBox().value).toBe('Saved goal');
    await armed(page);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    // The board's first prompt is still there to draft from, and is offered as an action only.
    expect(goalBox().value).toBe('');
    expect(text('[data-next-cockpit-held-kind="goal"] ~ *')).not.toContain('Ship the queue worker');
    expect(document.body.textContent).not.toContain('Draft from your first prompt');
    expect(control('held-save')?.getAttribute('aria-disabled')).toBe('true');
  });

  it('says it once after a discard: the result, and not the record under it as well', async () => {
    const DISCARDED = { annotation_discarded_at: 1000, annotation_revision_count: 0 };
    const page = mount({
      '/api/annotate': () => {
        page.state.data = withSentences({
          ...board(DISCARDED),
          annotate_discard: { ...SENTENCES },
        });
        return json({ ok: true, outcome: 'stored', persisted: true, withdrew: true });
      },
    });
    await settle(page);
    await armed(page);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    const said = text('.next-session-drift-caveats');
    expect(said).toContain(SENTENCES.stored);
    expect(said).not.toContain(SENTENCES.record);
    // The record stands once the result's own thirty seconds have lapsed.
    await act(async () => {
      page.clock.advance(31_000);
    });
    await page.settle();
    expect(text('.next-session-drift-caveats')).toContain(SENTENCES.record);
    expect(text('.next-session-drift-caveats')).not.toContain(SENTENCES.stored);
  });

  it('names a summary the server could not delete, and says Delete summary finishes it', async () => {
    const DISCARDED = { annotation_discarded_at: 1000, annotation_revision_count: 0 };
    const page = mount({
      '/api/annotate': () => {
        page.state.data = withSentences(board(DISCARDED));
        return json({
          ok: true,
          outcome: 'stored',
          persisted: true,
          withdrew: true,
          summary: 'unwritable',
        });
      },
    });
    await settle(page);
    await armed(page);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    expect(text('.next-cockpit-held-discard .next-cockpit-held-cue')).toBe(SENTENCES.summary_kept);
  });

  /* The sentence is chosen by what the server says happened to the summary store, never by the fact that one
     was asked for: "its summary" over a session that had none was the defect. */
  it.each([
    ['deleted', { summary: 'deleted', removed: 2 }, 'stored'],
    ['absent', { summary: 'absent', removed: 2 }, 'stored_no_summary'],
    ['unavailable', { summary: 'unavailable', removed: 2 }, 'summary_unavailable'],
    ['unwritable', { summary: 'unwritable', removed: 2 }, 'summary_kept'],
    ['an older server that names neither', {}, 'stored'],
  ] as const)('says what happened to the summary store: %s', async (_name, answer, sentence) => {
    const DISCARDED = { annotation_discarded_at: 1000, annotation_revision_count: 0 };
    const page = mount({
      '/api/annotate': () => {
        page.state.data = withSentences(board(DISCARDED));
        return json({ ok: true, outcome: 'stored', persisted: true, withdrew: true, ...answer });
      },
    });
    await settle(page);
    await armed(page);
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    expect(text('.next-cockpit-held-discard .next-cockpit-held-cue')).toBe(SENTENCES[sentence]);
  });

  it('says nothing was discarded when the store counted no revision, and keeps the drafts', async () => {
    const page = mount({
      '/api/annotate': () =>
        json({
          ok: true,
          outcome: 'stored',
          persisted: true,
          withdrew: true,
          summary: 'untouched',
          removed: 0,
        }),
    });
    await settle(page);
    type(goalBox(), 'half-typed words');
    page.state.data = withSentences(page.state.data as object);
    await page.poll(page.state.data);
    await press(discard());
    await act(async () => {
      page.clock.advance(1_300);
    });
    await press(discard());
    await settle(page);
    expect(text('.next-cockpit-held-discard .next-cockpit-held-cue')).toBe(SENTENCES.nothing);
    expect(goalBox().value).toBe('half-typed words');
  });

  it('disarms on Escape without leaving the page, and the next arm is a new warning', async () => {
    const page = mount();
    await settle(page);
    await armed(page);
    const before = page.router.getRoute();
    fireEvent.keyDown(discard() as Element, { key: 'Escape' });
    await page.settle();
    expect(discard()?.textContent).toBe('Discard everything');
    expect(text('#next-cockpit-cue-alert')).toBe('');
    expect(page.router.getRoute()).toEqual(before);
    await press(discard());
    expect(text('#next-cockpit-cue-alert')).toBe(SENTENCES.armed);
  });

  it('lapses on its own after thirty seconds, leaving a disarmed control', async () => {
    const page = mount();
    await settle(page);
    await armed(page);
    await act(async () => {
      page.clock.advance(31_000);
    });
    await page.settle();
    expect(discard()?.textContent).toBe('Discard everything');
    // The assertive region holds a warning only while that arm stands, so a lapse takes it back.
    expect(text('#next-cockpit-cue-alert')).toBe('');
    expect(page.posts()).toBe(0);
  });

  it('says the server refused, and that it cannot tell when no answer came, never "discarded"', async () => {
    const refused = mount({
      '/api/annotate': () => json({ ok: true, outcome: 'refused', persisted: false }),
    });
    await settle(refused);
    await armed(refused);
    await act(async () => {
      refused.clock.advance(1_300);
    });
    await press(discard());
    await settle(refused);
    expect(text('.next-cockpit-held-discard .next-cockpit-held-cue')).toBe(SENTENCES.refused);
    refused.unmount();
    const silent = mount({ '/api/annotate': () => new Response('<html>', { status: 200 }) });
    await settle(silent);
    await armed(silent);
    await act(async () => {
      silent.clock.advance(1_300);
    });
    await press(discard());
    await settle(silent);
    expect(text('.next-cockpit-held-discard .next-cockpit-held-cue')).toBe(
      'Compass did not answer, so this page cannot tell whether the words were discarded.',
    );
    expect(silent.allPosts()).toHaveLength(1);
  });

  it('withdraws the Intent log’s retained rows the moment the discard lands, before the board has refreshed', async () => {
    const page = mount({
      '/api/annotations': () =>
        json({
          annotations: [
            { harness: 'claude', sid: 's1', goal: 'Saved goal', revision: 2, revision_count: 1 },
          ],
          intent_revision: 'r1',
        }),
      '/api/annotate': () => json({ ok: true, outcome: 'stored', persisted: true, withdrew: true }),
    });
    await settle(page);
    // Visit the log so it holds the rows, then come back to the session and discard.
    await page.go('#n=intent');
    expect(document.body.textContent).toContain('Typed goal: Saved goal');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await armed(page);
    await act(async () => {
      page.clock.advance(1_300);
    });
    page.state.routes['/api/annotations'] = () => 'hold';
    await press(discard());
    await settle(page);
    await page.go('#n=intent');
    expect(document.body.textContent).not.toContain('Typed goal: Saved goal');
    expect(document.body.textContent).toContain('Reading the annotation store.');
  });
});
