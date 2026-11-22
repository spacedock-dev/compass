import type { ApiClient } from '../api/client';
import { compatSessKey, exactIdentity } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import type { Clock } from '../transport/ports';
import { beginLookup, settleLookup, type OriginLookup } from './registration';
import { createOutputStream, type OutputStream, type StreamSocket } from './stream';
import { createViewportState, type TerminalGeometry } from './viewport';
import type { XtermConstructor, XtermLike } from './xterm';

/* The one owner of the exact-session terminal: its registration lookups, the terminal and its screen, the
   output-only socket and the viewport state. It lives outside the rendered tree, because the terminal's
   lifetime is the session's and the navigation retention rules', not a component's. The legacy page keeps
   the mounted screen across a redraw and across leaving the Console tab, and disposes it only on Close,
   on opening another terminal, or when the registration turns out to be gone (`projectTerminalDispose` in
   `project.js`; docs/design-reader-state.md, "Cockpit disclosures and the mounted terminal"). A component
   that created these in an effect would drop the retained screen on every route change and, under
   StrictMode, open a second socket.

   Nothing here starts on its own. A lookup is a passive read; the renderer is requested, the terminal
   built and the socket opened only after the reader pressed Open terminal AND a viewport is on the page to
   show it. A renderer that fails to start is not retried by a redraw, a poll or a remount: the legacy page
   retried on every redraw, which would be a request per poll against a missing asset. */

export interface TerminalOwnerDeps {
  readonly client: Pick<ApiClient, 'getInteractionOrigin'>;
  readonly clock: Clock;
  readonly loader: { load(): Promise<XtermConstructor> };
  readonly openSocket: (url: string) => StreamSocket;
  readonly streamUrl: () => string;
  /** Creates the screen element, which outlives any one viewport. */
  readonly document: Document;
}

export interface TerminalSnapshot {
  /** The exact `harness:sid` key whose terminal is open, or null. At most one at a time. */
  readonly openKey: string | null;
  readonly lookups: ReadonlyMap<string, OriginLookup>;
  /** Whether the viewport is following live output; the Jump button shows when it is not. */
  readonly follow: boolean;
}

interface Live {
  readonly key: string;
  readonly screen: HTMLElement;
  terminal: XtermLike | null;
  stream: OutputStream | null;
  /** Set while the renderer is being requested, so a second attach asks for nothing. */
  loading: object | null;
  /** The renderer could not start; only an explicit Close and Open tries again. */
  failed: boolean;
}

const FALLBACK_FAILURE = 'Console cannot open because the terminal renderer could not start.';
const LOADING_TEXT = 'Loading the local terminal renderer.';

export function createTerminalOwner(deps: TerminalOwnerDeps) {
  const lookups = new Map<string, OriginLookup>();
  const controllers = new Set<AbortController>();
  const listeners = new Set<() => void>();
  const state = createViewportState();
  let openKey: string | null = null;
  let live: Live | null = null;
  let viewport: HTMLElement | null = null;
  let disposed = false;
  let snapshot: TerminalSnapshot = { openKey, lookups: new Map(), follow: true };

  function publish(): void {
    snapshot = { openKey, lookups: new Map(lookups), follow: state.follow() };
    for (const listener of [...listeners]) listener();
  }

  /* The renderer's own measurement of itself, or null before it has one. */
  function geometry(): TerminalGeometry | null {
    const terminal = live?.terminal;
    const screen = terminal?.element?.querySelector('.xterm-screen');
    if (!terminal?.buffer || !screen) return null;
    return {
      rows: terminal.rows,
      cursorY: terminal.buffer.active.cursorY,
      screenHeight: screen.getBoundingClientRect().height,
    };
  }

  /* The host takes the size of the rendered screen, so the viewport scrolls the real thing and short
     output is not pushed off the top by empty rows. */
  function sizeHost(current: Live): void {
    const screen = current.terminal?.element?.querySelector('.xterm-screen');
    if (!screen) return;
    const rect = screen.getBoundingClientRect();
    const width = Math.ceil(rect.width || 0);
    const height = Math.ceil(rect.height || 0);
    if (width > 0) current.screen.style.width = `${String(width)}px`;
    if (height > 0) current.screen.style.height = `${String(height)}px`;
  }

  const onScroll = (): void => {
    if (viewport && state.onScroll(viewport, geometry())) publish();
  };

  function disposeLive(): void {
    const closing = live;
    live = null;
    if (!closing) return;
    closing.stream?.dispose();
    closing.terminal?.dispose();
    closing.loading = null;
    closing.screen.remove();
  }

  function build(current: Live, Terminal: XtermConstructor): void {
    const palette = getComputedStyle(deps.document.documentElement);
    const background = palette.getPropertyValue('--sunk').trim();
    const terminal = new Terminal({
      disableStdin: true,
      cursorBlink: false,
      minimumContrastRatio: 4.5,
      // The cursor matches the background because stdin is disabled and a blinking block on read-only
      // output reads as an input affordance. xterm needs resolved CSS colours for its canvas.
      scrollback: 500,
      fontSize: 13,
      fontFamily: 'ui-monospace, monospace',
      theme: {
        background,
        foreground: palette.getPropertyValue('--ink').trim(),
        cursor: background,
        selectionBackground: palette.getPropertyValue('--line-hi').trim(),
        selectionForeground: palette.getPropertyValue('--on-accent').trim(),
      },
    });
    current.terminal = terminal;
    current.screen.textContent = '';
    terminal.open(current.screen);
    if (terminal.textarea) {
      terminal.textarea.readOnly = true;
      terminal.textarea.setAttribute('aria-label', 'Read-only terminal output');
    }
    if (viewport) state.bind(viewport, geometry());
    const hint = lookups.get(current.key);
    current.stream = createOutputStream({
      url: deps.streamUrl(),
      openSocket: deps.openSocket,
      clock: deps.clock,
      originHint: hint && hint.state !== 'loading' ? (hint.data.origin_id_hint ?? '') : '',
      terminal,
      wanted: () => !disposed && live === current,
      following: () => state.follow(),
      scrollToLive: () => {
        if (viewport) state.afterOutput(viewport, geometry());
      },
      sized: () => sizeHost(current),
    });
    current.stream.connect();
  }

  /* Requests the renderer once, and builds the terminal only if a viewport is still there to show it. A
     load that finishes after the reader left builds nothing; coming back asks again, which is a cached
     promise and no second request. */
  function ensureTerminal(): void {
    const current = live;
    if (!current || current.terminal || current.loading || current.failed || !viewport) return;
    const token = {};
    current.loading = token;
    deps.loader
      .load()
      .then((Terminal) => {
        if (live !== current || current.loading !== token) return;
        current.loading = null;
        if (!viewport) return;
        build(current, Terminal);
      })
      .catch((error: unknown) => {
        if (live !== current || current.loading !== token) return;
        current.loading = null;
        current.failed = true;
        // `build` throwing lands here too, which is why the message falls back rather than assuming a load.
        current.screen.textContent = (error instanceof Error && error.message) || FALLBACK_FAILURE;
      });
  }

  function close(): void {
    if (disposed) return;
    openKey = null;
    disposeLive();
    publish();
  }

  return {
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: (): TerminalSnapshot => snapshot,

    /* A passive read of one exact session's registration. The next revision re-checks it, and the settled
       answer stays on screen while that read is in flight. */
    lookup(identity: SessionIdentity, revision: number): void {
      const exact = exactIdentity(identity);
      if (disposed || !exact) return;
      const key = compatSessKey(exact);
      const next = beginLookup(lookups.get(key), revision);
      if (!next) return;
      lookups.set(key, next);
      publish();
      const controller = new AbortController();
      controllers.add(controller);
      void deps.client.getInteractionOrigin(exact, controller.signal).then((result) => {
        controllers.delete(controller);
        if (disposed) return;
        const settled = settleLookup(result, revision);
        if (!settled) {
          const held = lookups.get(key);
          if (held && held.state !== 'loading') lookups.set(key, { ...held, loading: false });
          return;
        }
        lookups.set(key, settled);
        // A registration that is gone takes the screen with it, as it did on the legacy page.
        if (openKey === key && settled.state !== 'registered') close();
        else publish();
      });
    },

    /* The reader pressed Open terminal. Only a registered session can be opened, and any other open
       terminal is let go of first: one terminal at a time, and a fresh one starts at the top following. */
    open(key: string): void {
      if (disposed || lookups.get(key)?.state !== 'registered') return;
      disposeLive();
      openKey = key;
      state.reset();
      const screen = deps.document.createElement('div');
      screen.id = 'pc-terminal-screen';
      screen.className = 'pc-terminal-screen';
      screen.textContent = LOADING_TEXT;
      live = { key, screen, terminal: null, stream: null, loading: null, failed: false };
      publish();
    },

    close,

    jump(): void {
      if (disposed || !viewport) return;
      const before = state.follow();
      state.jump(viewport, geometry());
      if (!before) publish();
    },

    /* The viewport is on the page: put the retained screen in it, restore or follow the scroll position
       and start the terminal if it has not started. The returned function takes the screen back out and
       nothing more, so leaving the page, StrictMode's second effect and a remount are all the same cheap
       operation and none of them can open a second socket. */
    attach(element: HTMLElement, key: string): () => void {
      if (disposed || !live || live.key !== key || openKey !== key) return () => undefined;
      viewport = element;
      const current = live;
      element.append(current.screen);
      element.addEventListener('scroll', onScroll);
      state.bind(element, geometry());
      ensureTerminal();
      return () => {
        element.removeEventListener('scroll', onScroll);
        if (current.screen.parentElement === element) current.screen.remove();
        if (viewport === element) viewport = null;
      };
    },

    /* What it holds, for a test or a browser probe to see a leak. */
    stats() {
      return {
        lookups: lookups.size,
        pendingReads: controllers.size,
        terminals: live?.terminal ? 1 : 0,
        sockets: live?.stream?.connected() ? 1 : 0,
        attached: live !== null && viewport !== null,
        openKey,
      };
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const controller of controllers) controller.abort();
      controllers.clear();
      disposeLive();
      viewport = null;
      openKey = null;
      listeners.clear();
    },
  };
}

export type TerminalOwner = ReturnType<typeof createTerminalOwner>;
