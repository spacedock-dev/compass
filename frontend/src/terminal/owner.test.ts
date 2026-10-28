// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import type { ApiResult, InteractionOrigin, SessionIdentity } from '../api/types';
import { createFakeClock } from '../transport/testing';
import { createTerminalOwner, type TerminalOwnerDeps } from './owner';
import { FakeSocket, FakeXterm, instances, viewportElement } from './testing';
import type { XtermConstructor } from './xterm';

/* ---------------------------------------------------------------------------------------------
   Doubles. The owner is the one place that holds the terminal, its socket and the lookups, and every
   test below is about what it opens, what it keeps across a remount and what it lets go of. */

const REGISTERED: ApiResult<InteractionOrigin> = {
  kind: 'ok',
  status: 200,
  revision: '',
  body: {
    state: 'registered',
    origin: { session_name: 'smoke', window_index: 0, pane_index: 0 },
    origin_id_hint: 'abcd1234',
  } as InteractionOrigin,
};

interface Pending {
  readonly identity: SessionIdentity;
  readonly signal: AbortSignal | undefined;
  resolve(result: ApiResult<InteractionOrigin>): void;
}

function setup(options: { loadFails?: Error } = {}) {
  instances.length = 0;
  const clock = createFakeClock();
  const sockets: FakeSocket[] = [];
  const reads: Pending[] = [];
  const loads: { resolve(): void; reject(error: Error): void }[] = [];
  const loadCalls = { count: 0 };
  let shared: Promise<XtermConstructor> | null = null;
  const doc = document.implementation.createHTMLDocument('terminal');
  const deps: TerminalOwnerDeps = {
    client: {
      getInteractionOrigin: (identity, signal) =>
        new Promise((resolve) => {
          reads.push({ identity, signal, resolve });
        }),
    },
    clock,
    /* The real loader shares one promise while it is pending and after it resolved, and forgets a
       rejected one so a later press can try again; this one does the same, and `loads` holds one entry
       per underlying request, which is what the page's network panel would show. */
    loader: {
      load: () => {
        loadCalls.count += 1;
        if (shared) return shared;
        const pending = new Promise<XtermConstructor>((resolve, reject) => {
          loads.push({ resolve: () => resolve(FakeXterm as unknown as XtermConstructor), reject });
          if (options.loadFails) reject(options.loadFails);
        });
        shared = pending;
        pending.catch(() => {
          if (shared === pending) shared = null;
        });
        return pending;
      },
    },
    openSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    streamUrl: () => 'ws://127.0.0.1:1/api/interaction/stream',
    document: doc,
  };
  const owner = createTerminalOwner(deps);
  const settle = async () => {
    for (let turn = 0; turn < 8; turn += 1) await Promise.resolve();
  };
  return { owner, clock, sockets, reads, loads, loadCalls, settle, doc };
}

const ALPHA: SessionIdentity = { harness: 'codex', sid: 'alpha' };
const BETA: SessionIdentity = { harness: 'codex', sid: 'beta' };
const ALPHA_KEY = 'codex:alpha';

async function register(t: ReturnType<typeof setup>, identity = ALPHA, revision = 1) {
  t.owner.lookup(identity, revision);
  t.reads.at(-1)?.resolve(REGISTERED);
  await t.settle();
}

const refused = (reason: string): ApiResult<InteractionOrigin> => ({
  kind: 'ok',
  status: 200,
  revision: '',
  body: { state: 'refused', reason } as InteractionOrigin,
});

const streamed = (sequence: number, data: string) => ({
  state: 'streamed',
  sequence,
  origin_id_hint: 'abcd1234',
  chunks: [{ sequence, data, cols: 80, rows: 24 }],
});

/* ---------------------------------------------------------------------------------------------- */

describe('the registration lookup', () => {
  it('asks for the exact harness and sid, once for a revision, and again for the next', async () => {
    const t = setup();
    t.owner.lookup(ALPHA, 1);
    t.owner.lookup(ALPHA, 1);
    expect(t.reads).toHaveLength(1);
    expect(t.reads[0]?.identity).toEqual(ALPHA);
    t.reads[0]?.resolve(REGISTERED);
    await t.settle();
    t.owner.lookup(ALPHA, 1);
    expect(t.reads).toHaveLength(1);
    t.owner.lookup(ALPHA, 2);
    expect(t.reads).toHaveLength(2);
  });

  it('keeps the settled answer on screen while the next revision is checked', async () => {
    const t = setup();
    await register(t);
    t.owner.lookup(ALPHA, 2);
    expect(t.owner.getSnapshot().lookups.get(ALPHA_KEY)).toMatchObject({
      state: 'registered',
      loading: true,
    });
  });

  it('sends nothing for an identity that is not exact, and never from a display id', () => {
    const t = setup();
    t.owner.lookup({ harness: 'codex', sid: '' }, 1);
    t.owner.lookup({ harness: '', sid: 'x' }, 1);
    t.owner.lookup({ harness: ' ', sid: 'x' }, 1);
    expect(t.reads).toHaveLength(0);
  });

  it('keeps the two sessions that share a sid apart, by harness', async () => {
    const t = setup();
    await register(t, { harness: 'claude', sid: 'shared' });
    t.owner.lookup({ harness: 'codex', sid: 'shared' }, 1);
    expect(t.reads).toHaveLength(2);
    expect(t.owner.getSnapshot().lookups.get('claude:shared')?.state).toBe('registered');
    expect(t.owner.getSnapshot().lookups.get('codex:shared')?.state).toBe('loading');
  });

  it('aborts only its own reads on dispose, and ignores an answer that arrives after', async () => {
    const t = setup();
    t.owner.lookup(ALPHA, 1);
    const read = t.reads[0];
    expect(read?.signal?.aborted).toBe(false);
    t.owner.dispose();
    expect(read?.signal?.aborted).toBe(true);
    read?.resolve(REGISTERED);
    await t.settle();
    expect(t.owner.getSnapshot().lookups.get(ALPHA_KEY)?.state).toBe('loading');
  });
});

describe('opening is an explicit act', () => {
  it('loads no renderer, opens no socket and starts no terminal until a viewport is attached', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    await t.settle();
    expect(t.loads).toHaveLength(0);
    expect(t.sockets).toHaveLength(0);
    expect(instances).toHaveLength(0);
    expect(t.owner.getSnapshot().openKey).toBe(ALPHA_KEY);
  });

  it('opens exactly one terminal and one socket for one open, however often the viewport is attached', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const viewport = viewportElement();
    // StrictMode's mount, cleanup, mount, before the renderer has loaded.
    const first = t.owner.attach(viewport, ALPHA_KEY);
    first();
    t.owner.attach(viewport, ALPHA_KEY);
    expect(t.loads).toHaveLength(1);
    // Asked for once: the second attach found the first still waiting and asked for nothing.
    expect(t.loadCalls.count).toBe(1);
    t.loads[0]?.resolve();
    await t.settle();
    expect(instances).toHaveLength(1);
    expect(t.sockets).toHaveLength(1);
    // And again after it is running.
    const again = t.owner.attach(viewport, ALPHA_KEY);
    again();
    t.owner.attach(viewport, ALPHA_KEY);
    await t.settle();
    expect(instances).toHaveLength(1);
    expect(t.sockets).toHaveLength(1);
    expect(t.loads).toHaveLength(1);
  });

  it('refuses to open a session whose bridge has not said it is registered', async () => {
    const t = setup();
    t.owner.open(ALPHA_KEY);
    expect(t.owner.getSnapshot().openKey).toBeNull();
    t.owner.lookup(ALPHA, 1);
    t.owner.open(ALPHA_KEY);
    expect(t.owner.getSnapshot().openKey).toBeNull();
    t.reads[0]?.resolve(refused('session-mismatch'));
    await t.settle();
    t.owner.open(ALPHA_KEY);
    expect(t.owner.getSnapshot().openKey).toBeNull();
  });

  it('ignores an attach for a key that is not the open one', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), 'codex:other')();
    expect(t.loads).toHaveLength(0);
  });

  it('configures the renderer read-only: no stdin, no blinking cursor, a labelled input that cannot be edited', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    const terminal = instances[0];
    expect(terminal?.options).toMatchObject({
      disableStdin: true,
      cursorBlink: false,
      scrollback: 500,
    });
    expect(terminal?.options.theme.cursor).toBe(terminal?.options.theme.background);
    expect(terminal?.textarea?.readOnly).toBe(true);
    expect(terminal?.textarea?.getAttribute('aria-label')).toBe('Read-only terminal output');
  });

  it('does not create the terminal when the renderer finishes loading with nothing to show it in', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const detach = t.owner.attach(viewportElement(), ALPHA_KEY);
    detach();
    t.loads[0]?.resolve();
    await t.settle();
    expect(instances).toHaveLength(0);
    expect(t.sockets).toHaveLength(0);
    // Coming back finishes the job, once.
    t.owner.attach(viewportElement(), ALPHA_KEY);
    await t.settle();
    expect(instances).toHaveLength(1);
    expect(t.sockets).toHaveLength(1);
  });
});

describe('leaving and coming back', () => {
  async function running() {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const viewport = viewportElement();
    const detach = t.owner.attach(viewport, ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    return { t, viewport, detach };
  }

  it('binds the socket to the origin the exact session registered: a frame from another pane is never drawn', async () => {
    // The stream URL names no session. The origin hint the lookup returned is the only thing tying this socket to
    // this harness and sid, so the owner must hand that hint on, and a frame that carries another one must close it.
    const { t } = await running();
    t.sockets[0]?.deliver({ ...streamed(1, 'another pane'), origin_id_hint: 'ffff0000' });
    expect(instances[0]?.written).toEqual([]);
    expect(t.sockets[0]?.closed).toBe(1);
    t.sockets[0]?.deliver(streamed(2, 'this pane'));
    expect(instances[0]?.written).toEqual(['this pane']);
  });

  it('keeps the terminal, its screen and its socket when the view unmounts, and puts the same ones back', async () => {
    const { t, viewport, detach } = await running();
    t.sockets[0]?.deliver(streamed(1, 'kept output'));
    const terminal = instances[0];
    const screen = terminal?.opened;
    expect(screen?.parentElement).toBe(viewport);
    detach();
    expect(screen?.isConnected).toBe(false);
    expect(terminal?.disposed).toBe(false);
    expect(t.sockets[0]?.closed).toBe(0);
    // Output keeps arriving while nobody is looking.
    t.sockets[0]?.deliver(streamed(2, 'while away'));
    const next = viewportElement();
    t.owner.attach(next, ALPHA_KEY);
    expect(screen?.parentElement).toBe(next);
    expect(instances).toHaveLength(1);
    expect(t.sockets).toHaveLength(1);
    expect(t.loads).toHaveLength(1);
    expect(terminal?.written).toEqual(['kept output', 'while away']);
  });

  it('restores the reader offset in the rebuilt scroll container, clamped to its real maximum', async () => {
    const { t, viewport, detach } = await running();
    viewport.scrollTop = 90;
    viewport.dispatchEvent(new Event('scroll'));
    expect(t.owner.getSnapshot().follow).toBe(false);
    detach();
    const shorter = viewportElement(400, 340);
    t.owner.attach(shorter, ALPHA_KEY);
    expect(shorter.scrollTop).toBe(60);
    const same = viewportElement(492, 340);
    const second = t.owner.attach(same, ALPHA_KEY);
    expect(same.scrollTop).toBe(60);
    second();
  });

  it('keeps an offset the rebuilt container still allows, exactly', async () => {
    const { t, viewport, detach } = await running();
    viewport.scrollTop = 90;
    viewport.dispatchEvent(new Event('scroll'));
    detach();
    const rebuilt = viewportElement(492, 340);
    t.owner.attach(rebuilt, ALPHA_KEY);
    expect(rebuilt.scrollTop).toBe(90);
    expect(t.owner.getSnapshot().follow).toBe(false);
  });

  it('takes its scroll listener off the viewport it leaves, rather than leaving one on a detached element', async () => {
    const { viewport, detach } = await running();
    const removed = vi.spyOn(viewport, 'removeEventListener');
    detach();
    expect(removed).toHaveBeenCalledWith('scroll', expect.any(Function));
  });

  it('removes its scroll listener from a viewport it has left', async () => {
    const { t, viewport, detach } = await running();
    detach();
    viewport.scrollTop = 40;
    viewport.dispatchEvent(new Event('scroll'));
    expect(t.owner.getSnapshot().follow).toBe(true);
  });
});

describe('following live output', () => {
  async function running() {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const viewport = viewportElement();
    t.owner.attach(viewport, ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    // The cursor on the last row: live is the 152 px scroll maximum of this container.
    const terminal = instances[0];
    if (terminal) terminal.buffer.active.cursorY = 23;
    return { t, viewport };
  }

  it('follows new output from the start, and publishes follow only when it changes', async () => {
    const { t, viewport } = await running();
    const seen: boolean[] = [];
    t.owner.subscribe(() => seen.push(t.owner.getSnapshot().follow));
    t.sockets[0]?.deliver(streamed(1, 'a'));
    expect(seen).toEqual([]);
    viewport.scrollTop = 20;
    viewport.dispatchEvent(new Event('scroll'));
    viewport.scrollTop = 21;
    viewport.dispatchEvent(new Event('scroll'));
    expect(seen).toEqual([false]);
  });

  it('stays where the reader scrolled while output arrives, and jumps back only when asked', async () => {
    const { t, viewport } = await running();
    viewport.scrollTop = 20;
    viewport.dispatchEvent(new Event('scroll'));
    t.sockets[0]?.deliver(streamed(1, 'a'));
    expect(viewport.scrollTop).toBe(20);
    t.owner.jump();
    expect(t.owner.getSnapshot().follow).toBe(true);
    expect(viewport.scrollTop).toBe(152);
  });

  it('follows again on its own once the reader scrolls back to within 2 px of live', async () => {
    const { t, viewport } = await running();
    viewport.scrollTop = 20;
    viewport.dispatchEvent(new Event('scroll'));
    viewport.scrollTop = 150;
    viewport.dispatchEvent(new Event('scroll'));
    expect(t.owner.getSnapshot().follow).toBe(true);
  });

  it('puts a newly opened terminal back at the top, following', async () => {
    const { t, viewport } = await running();
    viewport.scrollTop = 20;
    viewport.dispatchEvent(new Event('scroll'));
    t.owner.close();
    t.owner.open(ALPHA_KEY);
    expect(t.owner.getSnapshot().follow).toBe(true);
  });
});

describe('letting go', () => {
  it('closes the socket, disposes the terminal and removes the screen on Close, and reopening starts fresh', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    const terminal = instances[0];
    const screen = terminal?.opened;
    t.owner.close();
    expect(t.sockets[0]?.closed).toBe(1);
    expect(terminal?.disposed).toBe(true);
    expect(screen?.isConnected).toBe(false);
    expect(t.owner.getSnapshot().openKey).toBeNull();
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[1]?.resolve();
    await t.settle();
    expect(instances).toHaveLength(2);
    expect(t.sockets).toHaveLength(2);
    expect(t.sockets[1]?.closed).toBe(0);
  });

  it('lets go of the first terminal when another session is opened, and only that one', async () => {
    const t = setup();
    await register(t);
    await register(t, BETA);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    t.owner.open('codex:beta');
    expect(instances[0]?.disposed).toBe(true);
    expect(t.sockets[0]?.closed).toBe(1);
    t.owner.attach(viewportElement(), 'codex:beta');
    await t.settle();
    expect(instances).toHaveLength(2);
    expect(instances[1]?.disposed).toBe(false);
    expect(t.sockets).toHaveLength(2);
  });

  it('closes an open terminal whose registration is later found to be gone', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    t.owner.lookup(ALPHA, 2);
    t.reads.at(-1)?.resolve(refused('stale-registration'));
    await t.settle();
    expect(t.owner.getSnapshot().openKey).toBeNull();
    expect(instances[0]?.disposed).toBe(true);
    expect(t.sockets[0]?.closed).toBe(1);
  });

  it('closes an open terminal when the lookup fails, rather than leaving a screen it cannot vouch for', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    t.owner.lookup(ALPHA, 2);
    t.reads.at(-1)?.resolve({ kind: 'network-error' });
    await t.settle();
    expect(t.owner.getSnapshot().openKey).toBeNull();
    expect(t.owner.getSnapshot().lookups.get(ALPHA_KEY)).toMatchObject({
      data: { reason: 'lookup-failed' },
    });
  });

  it('keeps a terminal for a different session open when this session is found unregistered', async () => {
    const t = setup();
    await register(t);
    await register(t, BETA);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    t.owner.lookup(BETA, 2);
    t.reads.at(-1)?.resolve(refused('unregistered-origin'));
    await t.settle();
    expect(t.owner.getSnapshot().openKey).toBe(ALPHA_KEY);
    expect(instances[0]?.disposed).toBe(false);
  });

  it('disposes everything it owns, closes only its own socket and clears its timers', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    t.sockets[0]?.onclose?.({ code: 1006 });
    expect(t.clock.activeTimers()).toBe(1);
    t.owner.dispose();
    expect(t.clock.activeTimers()).toBe(0);
    expect(instances[0]?.disposed).toBe(true);
    t.clock.advance(10_000);
    expect(t.sockets).toHaveLength(1);
    t.owner.open(ALPHA_KEY);
    t.owner.lookup(ALPHA, 9);
    expect(t.reads).toHaveLength(1);
  });
});

describe('a renderer that cannot start', () => {
  it('says why on the screen, opens no socket, and does not try again until the reader presses Open again', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const viewport = viewportElement();
    t.owner.attach(viewport, ALPHA_KEY);
    t.loads[0]?.reject(
      new Error('Console cannot open because the local terminal script did not load.'),
    );
    await t.settle();
    expect(viewport.textContent).toBe(
      'Console cannot open because the local terminal script did not load.',
    );
    expect(t.sockets).toHaveLength(0);
    // A redraw, a poll or a remount is not a press.
    t.owner.attach(viewport, ALPHA_KEY)();
    t.owner.attach(viewport, ALPHA_KEY);
    await t.settle();
    expect(t.loads).toHaveLength(1);
    // Close and Open is.
    t.owner.close();
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    expect(t.loads).toHaveLength(2);
  });

  it('says a generic reason when the failure carried none', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const viewport = viewportElement();
    t.owner.attach(viewport, ALPHA_KEY);
    t.loads[0]?.reject(new Error(''));
    await t.settle();
    expect(viewport.textContent).toBe(
      'Console cannot open because the terminal renderer could not start.',
    );
  });
});

describe('output only', () => {
  it('transmits nothing when keys are pressed or text is pasted in the terminal', async () => {
    const t = setup();
    await register(t);
    t.owner.open(ALPHA_KEY);
    const viewport = viewportElement();
    document.body.append(viewport);
    t.owner.attach(viewport, ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    const terminal = instances[0];
    for (const target of [terminal?.textarea, terminal?.element, viewport]) {
      target?.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
      target?.dispatchEvent(new KeyboardEvent('keypress', { key: 'a', bubbles: true }));
      target?.dispatchEvent(new Event('paste', { bubbles: true }));
      target?.dispatchEvent(new Event('input', { bubbles: true }));
    }
    t.sockets[0]?.deliver(streamed(1, 'output'));
    t.sockets[0]?.onclose?.({ code: 1006 });
    t.clock.advance(1000);
    t.sockets[1]?.deliver(streamed(1, 'again'));
    t.owner.close();
    expect(t.sockets.map((socket) => socket.sent)).toEqual([0, 0]);
    viewport.remove();
  });
});

describe('what it reports', () => {
  it('counts what it holds, so a test can see a leak', async () => {
    const t = setup();
    expect(t.owner.stats()).toEqual({
      lookups: 0,
      pendingReads: 0,
      terminals: 0,
      sockets: 0,
      attached: false,
      openKey: null,
    });
    await register(t);
    t.owner.open(ALPHA_KEY);
    t.owner.attach(viewportElement(), ALPHA_KEY);
    t.loads[0]?.resolve();
    await t.settle();
    expect(t.owner.stats()).toEqual({
      lookups: 1,
      pendingReads: 0,
      terminals: 1,
      sockets: 1,
      attached: true,
      openKey: ALPHA_KEY,
    });
    t.owner.close();
    expect(t.owner.stats()).toEqual({
      lookups: 1,
      pendingReads: 0,
      terminals: 0,
      sockets: 0,
      attached: false,
      openKey: null,
    });
  });

  it('notifies subscribers of an open, a close and a lookup, and not of an unrelated scroll', async () => {
    const t = setup();
    let notified = 0;
    const off = t.owner.subscribe(() => {
      notified += 1;
    });
    t.owner.lookup(ALPHA, 1);
    expect(notified).toBe(1);
    t.reads[0]?.resolve(REGISTERED);
    await t.settle();
    expect(notified).toBe(2);
    t.owner.open(ALPHA_KEY);
    expect(notified).toBe(3);
    off();
    t.owner.close();
    expect(notified).toBe(3);
  });
});
