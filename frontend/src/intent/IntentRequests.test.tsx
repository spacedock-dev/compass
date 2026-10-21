import { openSelect } from '../../test/select';
import { act, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { json } from './testing';
import { board, control, goalBox, mountSession, text, type } from './panel.testing';

/* Nothing here starts a write, a notification, a clipboard action or a model reading from a mount, a second
   mount under StrictMode, a poll, a reconnect, a retry or a route change. The counts are requests the
   backend saw, by method and path, so a request the page forgot to mention is still counted. */

const fact = (id: string, at: number, summary: string) => ({
  fact_id: id,
  type: 'user_message',
  by: 'person:me',
  summary,
  at,
  source_session: { harness: 'claude', sid: 's1' },
});

const SEEDED = {
  store: { goal: 'Saved goal', lines: ['A line'], revision: 2 },
  session: { annotation_goal_saved_at: 500, annotation_at: 500 },
  routes: {
    '/api/project-context': () =>
      json({ semantic: { facts: [fact('f1', 600, 'Do it the careful way')] } }),
    '/api/annotations': () =>
      json({
        annotations: [
          { harness: 'claude', sid: 's1', goal: 'Saved goal', revision: 2, revision_count: 1 },
        ],
        intent_revision: 'r1',
      }),
  },
};

describe('the Intent surfaces start nothing on their own', () => {
  it('writes and asks nothing across a StrictMount, polls, an option list opening, a reconnect and route changes', async () => {
    const page = mountSession({ ...SEEDED, strict: true });
    await page.settle();
    await page.settle();
    expect(document.querySelector('[data-next-cockpit-direction-question]')).not.toBeNull();
    for (const generated of [1100, 1200, 1300]) {
      await page.poll({ ...(page.state.data as object), generated });
    }
    // The reader opens the prompt menu: a read, never a write.
    const select = document.querySelector('[data-next-cockpit-prompt-select]');
    if (select) {
      await openSelect(select as HTMLElement);
    }
    await page.go('#n=intent');
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    await page.back();
    await page.settle();
    /* The one POST drawing the question sends is the read of the open directions' words, so the question
       quotes what each choice acts on. It writes nothing and starts no model: nothing else is sent. */
    const sent = page.state.requests.filter((request) => request.method !== 'GET');
    expect(sent.length).toBeGreaterThan(0);
    for (const request of sent) {
      expect(request.path).toBe('/api/direction');
      expect(Object.keys(request.body ?? {}).sort()).toEqual(['fact_ids', 'harness', 'sid']);
    }
    expect(page.written).toEqual([]);
    expect(page.gets('/api/annotations')).toBe(1);
  });

  it('reads the observed record once per board revision per scope, however many times StrictMode mounts', async () => {
    const page = mountSession({ ...SEEDED, strict: true });
    await page.settle();
    await page.settle();
    // The project and the focused session, once each.
    expect(page.gets('/api/project-context')).toBe(2);
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    await page.settle();
    expect(page.gets('/api/project-context')).toBe(4);
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    await page.settle();
    expect(page.gets('/api/project-context')).toBe(4);
  });

  it('never reads the record, or draws an editor, while annotations are off', async () => {
    const page = mountSession({ ...SEEDED, strict: true });
    await page.settle();
    page.state.requests.length = 0;
    await page.poll({ ...(page.state.data as object), annotate: false, generated: 1100 });
    await page.settle();
    expect(goalBox()).toBeNull();
    /* The one read left is What the session has done reading its outline: that card is not an annotation and
       reads the focused context once per board revision whatever annotations say. The Intent card adds none,
       so nothing reads the project scope and the focused session is read once. */
    const reads = page.state.requests.filter((r) => r.path === '/api/project-context');
    expect(reads.filter((r) => !r.url.includes('session='))).toEqual([]);
    expect(reads).toHaveLength(1);
    expect(page.state.requests.filter((r) => r.method !== 'GET')).toEqual([]);
  });

  it('sends exactly one request for one press, however the control is pressed', async () => {
    const page = mountSession({
      ...SEEDED,
      routes: { ...SEEDED.routes, '/api/annotate': () => 'hold' },
    });
    await page.settle();
    await page.settle();
    type(goalBox(), 'Edited goal');
    const save = control('held-save') as Element;
    await act(async () => {
      fireEvent.click(save);
      fireEvent.click(save);
      fireEvent.keyDown(save, { key: 'Enter' });
      fireEvent.click(save);
    });
    expect(page.posts('/api/annotate')).toBe(1);
    // A poll, a refresh and a route change while it is open send nothing more and retry nothing.
    await page.poll({ ...(page.state.data as object), generated: 1100 });
    await page.go('#n=sessions');
    await page.go('#n=session:alpha%2Fapp:claude:s1');
    expect(page.posts('/api/annotate')).toBe(1);
    expect(text('.next-cockpit-held-footer')).toBeTypeOf('string');
    expect(board).toBeTypeOf('function');
  });
});
