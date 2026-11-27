import { openSelect, chooseSelect } from '../../test/select';
import { act, fireEvent } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StageConditions } from './StageConditions';
import { json, mountPanels } from './testing';

/* The press flow of a saved stage condition: one request per press, never retried, naming what the reader
   SAW, its refusal said where they read it, and focus given back only to a reader who has not moved on. */
const SCOPE = [{ harness: 'claude', sid: 's1' }];
const board = (revision: string, generated = 1000) => ({
  generated,
  sessions: [],
  tripwires: {
    enabled: true,
    sources: [
      {
        id: 'wf-1',
        workflow: 'Ship the queue',
        goal: 'Drain it',
        stages: ['plan', 'build', 'review'],
        generation: 1,
        ambiguous: false,
        sessions: [{ label: 'alpha', harness: 'claude', sid: 's1' }],
        entities: [{}],
        partial: false,
      },
    ],
    rules: [
      {
        id: 'wf-1',
        workflow: 'Ship the queue',
        stage: 'build',
        state: 'armed',
        available: true,
        revision,
        why: 'Armed',
        delivery_why: 'Server lane',
      },
    ],
  },
});
const saved = () => json({ ok: true });
const select = (): HTMLButtonElement =>
  document.querySelector('[data-stage-choice]') as HTMLButtonElement;
const button = (action: string): HTMLButtonElement =>
  document.querySelector(`[data-stage-action="${action}"]`) as HTMLButtonElement;
const cue = (): string => document.querySelector('[role="status"]')?.textContent ?? '';
const mount = (options: Parameters<typeof mountPanels>[1] = {}) =>
  mountPanels(
    <main id="app">
      <StageConditions sessions={SCOPE} />
    </main>,
    { data: board('r1'), ...options },
  );
const press = async (element: HTMLElement) => {
  await act(async () => {
    fireEvent.click(element);
  });
};

describe('nothing is sent until a press', () => {
  it('a mount, StrictMode and a poll send no request but the board reads', async () => {
    const page = mount();
    await page.settle();
    await page.poll(board('r1', 1001));
    expect(page.allPosts()).toEqual([]);
    expect(
      page.state.requests.every(({ path }) => path === '/api/data' || path === '/api/plan'),
    ).toBe(true);
  });
});

describe('Save', () => {
  it('sends the exact request once, shows it busy, and says it was saved', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    await chooseSelect(select(), 'review');
    await press(button('save'));
    expect(page.allPosts()).toHaveLength(1);
    expect(page.allPosts()[0]?.path).toBe('/api/tripwire');
    expect(page.allPosts()[0]?.body).toEqual({
      action: 'save',
      id: 'wf-1',
      stage: 'review',
      expected_revision: 'r1',
    });
    expect(cue()).toBe('Saving…');
    for (const control of [select(), button('save'), button('rearm'), button('remove')])
      expect((control as HTMLButtonElement).disabled).toBe(true);
    // A second press while the first is out sends nothing.
    await press(button('save'));
    expect(page.allPosts()).toHaveLength(1);
    page.state.data = board('r2', 1005);
    await page.release('/api/tripwire', saved());
    await page.settle();
    expect(cue()).toBe('Saved.');
    expect(button('save').disabled).toBe(false);
    expect(page.gets()).toBeGreaterThan(1);
    expect(page.allPosts()).toHaveLength(1);
  });

  it('says the server’s own refusal where the reader reads it, and does not retry', async () => {
    const page = mount({
      routes: {
        '/api/tripwire': () =>
          json({ ok: false, error: 'The saved condition changed; reload.' }, 409),
      },
    });
    await page.settle();
    await press(button('save'));
    await page.settle();
    expect(cue()).toBe('The saved condition changed; reload.');
    await page.advance(60_000);
    expect(page.allPosts()).toHaveLength(1);
    expect(button('save').disabled).toBe(false);
  });

  it('says it could not save when the answer is lost or is not an answer', async () => {
    for (const answer of [
      () => new Response('<html>', { status: 200 }),
      () => json({ ok: false }, 200),
    ]) {
      const page = mount({ routes: { '/api/tripwire': answer } });
      await page.settle();
      await press(button('save'));
      await page.settle();
      expect(cue()).toBe('Could not save the stage condition.');
      page.unmount();
    }
  });

  it('refuses a choice the source no longer offers without sending anything', async () => {
    const stale = board('r1');
    stale.tripwires.rules[0] = { ...stale.tripwires.rules[0], stage: 'ship' } as never;
    const page = mount({ data: stale });
    await page.settle();
    expect(button('save').disabled).toBe(true);
    await press(button('save'));
    expect(page.allPosts()).toEqual([]);
  });

  it('names the revision the reader SAW, not a newer one the board accepted while a list was open', async () => {
    const page = mount();
    await page.settle();
    // An open choice holds a poll back from the screen: the board is newer than the card.
    await openSelect(select());
    await page.poll(board('r2', 1002));
    expect(select().isConnected).toBe(true);
    await press(button('remove'));
    expect(page.allPosts()[0]?.body).toMatchObject({ action: 'remove', expected_revision: 'r1' });
  });
});

describe('a press is one request', () => {
  it('two presses in one tick send one', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    await act(async () => {
      fireEvent.click(button('save'));
      fireEvent.click(button('save'));
    });
    expect(page.allPosts()).toHaveLength(1);
    // The second press is turned away quietly, not reported as a failure of the first.
    expect(cue()).toBe('Saving…');
  });

  it('is bounded: a request nobody answers is abandoned and the card is not left busy', async () => {
    const page = mount({
      routes: {
        '/api/tripwire': (request) =>
          new Promise<Response>((_resolve, reject) => {
            request.signal?.addEventListener('abort', () =>
              reject(new DOMException('gone', 'AbortError')),
            );
          }),
      },
    });
    await page.settle();
    await press(button('save'));
    expect(button('save').disabled).toBe(true);
    await page.advance(15_000);
    await page.settle();
    expect(cue()).toBe('Could not save the stage condition.');
    expect(button('save').disabled).toBe(false);
    expect(page.allPosts()).toHaveLength(1);
  });

  it('shows what the server holds after an abandoned request, with one refresh and no stronger a cue', async () => {
    const page = mount({
      routes: {
        '/api/tripwire': (request) =>
          new Promise<Response>((_resolve, reject) => {
            request.signal?.addEventListener('abort', () =>
              reject(new DOMException('gone', 'AbortError')),
            );
          }),
      },
    });
    await page.settle();
    const refresh = vi.spyOn(page.shell.runtime, 'refresh');
    await press(button('save'));
    expect(refresh).not.toHaveBeenCalled();
    await page.advance(15_000);
    await page.settle();
    // The cue says what the page knows, which is that it did not hear back; the board is read once so the
    // card shows whatever the server kept.
    expect(cue()).toBe('Could not save the stage condition.');
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(page.allPosts()).toHaveLength(1);
  });

  it('does not refresh after an answered refusal: the server said what it holds', async () => {
    const page = mount({
      routes: { '/api/tripwire': () => json({ ok: false, error: 'No.' }, 409) },
    });
    await page.settle();
    const refresh = vi.spyOn(page.shell.runtime, 'refresh');
    await press(button('save'));
    await page.settle();
    expect(cue()).toBe('No.');
    expect(refresh).not.toHaveBeenCalled();
  });

  it('drops the choice once it is saved, so the card shows what the board says', async () => {
    // The board still says "build" after the save, so a kept draft would show "review" against it.
    const page = mount({ routes: { '/api/tripwire': saved } });
    await page.settle();
    await chooseSelect(select(), 'review');
    await press(button('save'));
    await page.settle();
    expect(cue()).toBe('Saved.');
    expect(select().textContent).toBe('build');
  });
});

describe('Rearm and Remove', () => {
  it('send their action with the saved stage and say so', async () => {
    const page = mount({ routes: { '/api/tripwire': saved } });
    await page.settle();
    await press(button('rearm'));
    await page.settle();
    expect(page.allPosts()[0]?.body).toEqual({
      action: 'rearm',
      id: 'wf-1',
      stage: 'build',
      expected_revision: 'r1',
    });
    expect(cue()).toBe('Rearmed; baseline reset.');
    await press(button('remove'));
    await page.settle();
    expect(cue()).toBe('Removed.');
  });
});

describe('the reader’s choice and cue', () => {
  it('survive the card leaving and returning, per workflow', async () => {
    const page = mount({
      routes: { '/api/tripwire': () => json({ ok: false, error: 'No.' }, 409) },
    });
    await page.settle();
    await chooseSelect(select(), 'review');
    await press(button('save'));
    await page.settle();
    page.show(<p>elsewhere</p>);
    page.show(
      <main id="app">
        <StageConditions sessions={SCOPE} />
      </main>,
    );
    await page.settle();
    expect(select().textContent).toBe('review');
    expect(cue()).toBe('No.');
  });
});

/* jsdom keeps a disabled control as the active element, where a browser's focus fix-up moves it to the body.
   The browser's behaviour is modelled by reporting the body, and what is asserted is whether focus was asked
   for; `console-parity.mjs` proves the real thing in Chromium. */
const lostFocus = () => vi.spyOn(document, 'activeElement', 'get').mockReturnValue(document.body);
const focusCalls = () => vi.spyOn(HTMLElement.prototype, 'focus');

describe('focus after a press', () => {
  afterEach(() => vi.restoreAllMocks());

  it('returns to the pressed control when nothing has taken it and the reader has not moved on', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    button('save').focus();
    await press(button('save'));
    lostFocus();
    const focus = focusCalls();
    await page.release('/api/tripwire', saved());
    await page.settle();
    expect(focus.mock.instances).toEqual([button('save')]);
  });

  it('does not take focus for a control the reader pressed without ever focusing', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    await press(button('save'));
    lostFocus();
    const focus = focusCalls();
    await page.release('/api/tripwire', saved());
    await page.settle();
    expect(focus).not.toHaveBeenCalled();
  });

  it('is not taken back once the reader has pressed a key since', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    button('save').focus();
    await press(button('save'));
    lostFocus();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    const focus = focusCalls();
    await page.release('/api/tripwire', saved());
    await page.settle();
    expect(focus).not.toHaveBeenCalled();
  });

  it('is not taken back from a control the reader has put focus on', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    button('save').focus();
    await press(button('save'));
    const elsewhere = document.createElement('input');
    document.body.append(elsewhere);
    elsewhere.focus();
    const focus = focusCalls();
    await page.release('/api/tripwire', saved());
    await page.settle();
    expect(focus).not.toHaveBeenCalled();
    elsewhere.remove();
  });

  it('is not carried to the same workflow’s card on another page the reader went to meanwhile', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    button('save').focus();
    await press(button('save'));
    // Back to a page that draws a card for the same workflow, as the Projects list does.
    page.show(
      <div id="projects">
        <StageConditions sessions={null} />
      </div>,
    );
    await page.settle();
    lostFocus();
    const focus = focusCalls();
    await page.release('/api/tripwire', saved());
    await page.settle();
    expect(focus).not.toHaveBeenCalled();
  });

  it('is not left waiting for a page that has gone: a card that returns later takes nothing', async () => {
    const page = mount({ routes: { '/api/tripwire': () => 'hold' } });
    await page.settle();
    button('save').focus();
    await press(button('save'));
    page.show(<p>elsewhere</p>);
    lostFocus();
    await page.release('/api/tripwire', saved());
    await page.settle();
    const focus = focusCalls();
    page.show(
      <main id="app">
        <StageConditions sessions={SCOPE} />
      </main>,
    );
    await page.settle();
    expect(focus).not.toHaveBeenCalled();
    expect(page.allPosts()).toHaveLength(1);
  });
});
