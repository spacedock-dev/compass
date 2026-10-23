import { createContext, useCallback, useContext, useSyncExternalStore } from 'react';
import type { Controls } from '../controls/kit';
import type { DisplayGate } from '../controls/displayGate';
import { useDisplayedSelector } from '../controls/useDisplayed';
import type { RouteInput, Route } from '../router/grammar';
import type { Router } from '../router/router';
import type { BoardSnapshot } from '../store/board';
import type { BrowserRuntime } from '../transport/browser';
import type { Clock, Environment } from '../transport/ports';
import type { Announcer } from './announcer';

/* What the page needs from the browser beyond the runtime, so a test can stand in for it. */
export interface ShellHost {
  /** `location.reload()`: pressed only on the build notice's Reload. */
  reload(): void;
  /** Whether the live stream exists here, which decides the fallback poll the stalled notice quotes. */
  readonly streamSupported: boolean;
}

/* Everything the page is built from, assembled once per document (`createShell`) and held outside the
   rendered tree: the board's runtime and store, the route, the live regions, the shared controls and
   the gate that decides when a poll reaches the screen. A component reads these through the hooks
   below and never constructs one, which is what keeps StrictMode and a remount from making a second
   owner of anything. */
export interface Shell {
  readonly runtime: BrowserRuntime;
  readonly router: Router;
  readonly announcer: Announcer;
  readonly display: DisplayGate;
  readonly controls: Controls;
  readonly clock: Clock;
  /** The browser surface the transport reads, which the Live monitor's lease also uses for this tab's id,
      its visibility and its stop beacon. */
  readonly env: Environment;
  readonly host: ShellHost;
}

export const ShellContext = createContext<Shell | null>(null);

export function useShell(): Shell {
  const shell = useContext(ShellContext);
  if (!shell) throw new Error('A shell component was rendered outside the shell.');
  return shell;
}

export function useRoute(): Route {
  const { router } = useShell();
  return useSyncExternalStore(router.subscribe, router.getRoute);
}

export function useNavigate(): (route: RouteInput) => void {
  const { router } = useShell();
  return useCallback((route: RouteInput) => router.navigate(route), [router]);
}

/* What the reader is SHOWN, which is the store's board except while a native option list or a
   disclosure's motion holds a poll back. The selector must return a stable value while its slice is
   unchanged, which the memoised selectors in `store/selectors` and `./derive` do. */
export function useDisplayed<T>(selector: (snapshot: BoardSnapshot) => T): T {
  return useDisplayedSelector(useShell().display, selector);
}
